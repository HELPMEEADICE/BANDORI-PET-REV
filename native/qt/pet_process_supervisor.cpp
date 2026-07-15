#include "pet_process_supervisor.h"

#include "bandori_config_ffi.h"
#include "shared_memory_line_queue.h"

#include <QByteArray>
#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDir>
#include <QFileInfo>
#include <QProcessEnvironment>
#include <QStandardPaths>
#include <QUuid>

#include <algorithm>
#include <utility>

namespace bandori {

namespace {
constexpr int kStableRunMsec = 30'000;
constexpr int kMaximumConsecutiveRestarts = 4;
constexpr int kTerminateGraceMsec = 1'500;
}

PetProcessSupervisor::PetProcessSupervisor(QObject* parent)
    : QObject(parent) {
    process_.setProcessChannelMode(QProcess::SeparateChannels);
    restartTimer_.setSingleShot(true);
    terminateTimer_.setSingleShot(true);
    killTimer_.setSingleShot(true);
    ipcPollTimer_.setInterval(30);

    connect(&restartTimer_, &QTimer::timeout, this, &PetProcessSupervisor::launchNow);
    connect(&terminateTimer_, &QTimer::timeout, this, [this]() {
        if (process_.state() != QProcess::NotRunning) {
            process_.terminate();
            killTimer_.start(kTerminateGraceMsec);
        }
    });
    connect(&killTimer_, &QTimer::timeout, this, [this]() {
        if (process_.state() != QProcess::NotRunning) {
            emit statusChanged(QStringLiteral("Pet renderer did not stop; killing it"));
            process_.kill();
        }
    });
    connect(&ipcPollTimer_, &QTimer::timeout, this, &PetProcessSupervisor::pollIpcMessages);
    connect(
        &process_,
        QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished),
        this,
        &PetProcessSupervisor::handleFinished);
    connect(&process_, &QProcess::readyReadStandardError, this, [this]() {
        const QString message = QString::fromUtf8(process_.readAllStandardError()).trimmed();
        if (!message.isEmpty()) {
            emit rendererLog(message);
        }
    });
    connect(&process_, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart) {
            emit statusChanged(
                QStringLiteral("Failed to start pet renderer: %1").arg(process_.errorString()));
            scheduleRestart();
        }
    });
}

PetProcessSupervisor::~PetProcessSupervisor() {
    stop();
    if (process_.state() != QProcess::NotRunning) {
        process_.kill();
        process_.waitForFinished(1'000);
    }
}

void PetProcessSupervisor::start(PetLaunchSpec spec) {
    spec.width = std::max(spec.width, 1);
    spec.height = std::max(spec.height, 1);
    spec.fps = std::clamp(spec.fps, 10, 240);
    spec.opacity = std::clamp(spec.opacity, 0.05, 1.0);
    spec.lipSyncMaxOpen = std::clamp(spec.lipSyncMaxOpen, 0.0, 1.0);
    spec.hitAlphaThreshold = std::clamp(spec.hitAlphaThreshold, 0, 255);
    spec_ = std::move(spec);
    restartTimer_.stop();
    consecutiveFailures_ = 0;
    if (process_.state() != QProcess::NotRunning) {
        stopping_ = true;
        relaunchAfterStop_ = true;
        replaceIpcSessionAfterStop_ = true;
        emit statusChanged(QStringLiteral("Replacing pet renderer"));
        requestProcessStop();
        return;
    }
    if (!initializeIpcSession()) {
        stopping_ = true;
        return;
    }
    stopping_ = false;
    relaunchAfterStop_ = false;
    replaceIpcSessionAfterStop_ = false;
    launchNow();
}

void PetProcessSupervisor::stop() {
    stopping_ = true;
    relaunchAfterStop_ = false;
    replaceIpcSessionAfterStop_ = false;
    restartTimer_.stop();
    ipcPollTimer_.stop();
    if (process_.state() == QProcess::NotRunning) {
        terminateTimer_.stop();
        killTimer_.stop();
        return;
    }
    emit statusChanged(QStringLiteral("Stopping pet renderer"));
    requestProcessStop();
}

bool PetProcessSupervisor::isRunning() const {
    return process_.state() != QProcess::NotRunning;
}

void PetProcessSupervisor::launchNow() {
    if (stopping_ || process_.state() != QProcess::NotRunning) {
        return;
    }
    const QString program = rendererProgram();
    if (program.isEmpty()) {
        emit statusChanged(QStringLiteral("Pet renderer executable was not found"));
        scheduleRestart();
        return;
    }
    process_.setProgram(program);
    process_.setWorkingDirectory(spec_.projectRoot);
    QProcessEnvironment environment = QProcessEnvironment::systemEnvironment();
    environment.insert(QStringLiteral("BANDORI_PET_IPC_SERVER_NAME"), ipcSessionName_);
    process_.setProcessEnvironment(environment);
    process_.setArguments({
        QStringLiteral("--project-root"),
        spec_.projectRoot,
        QStringLiteral("--user-models"),
        spec_.userModelsRoot,
        QStringLiteral("--model"),
        spec_.modelPath,
        QStringLiteral("--character"),
        spec_.character,
        QStringLiteral("--format"),
        spec_.format,
        QStringLiteral("--width"),
        QString::number(spec_.width),
        QStringLiteral("--height"),
        QString::number(spec_.height),
        QStringLiteral("--x"),
        QString::number(spec_.x),
        QStringLiteral("--y"),
        QString::number(spec_.y),
        QStringLiteral("--fps"),
        QString::number(spec_.fps),
        QStringLiteral("--opacity"),
        QString::number(spec_.opacity, 'f', 3),
        QStringLiteral("--lip-sync-max-open"),
        QString::number(spec_.lipSyncMaxOpen, 'f', 3),
        QStringLiteral("--hit-alpha-threshold"),
        QString::number(spec_.hitAlphaThreshold),
        QStringLiteral("--drag-locked"),
        spec_.dragLocked ? QStringLiteral("true") : QStringLiteral("false"),
        QStringLiteral("--move-all-roles-together"),
        spec_.moveAllRolesTogether ? QStringLiteral("true") : QStringLiteral("false"),
        QStringLiteral("--head-tracking-enabled"),
        spec_.headTrackingEnabled ? QStringLiteral("true") : QStringLiteral("false"),
        QStringLiteral("--mutual-gaze-enabled"),
        spec_.mutualGazeEnabled ? QStringLiteral("true") : QStringLiteral("false"),
        QStringLiteral("--parent-pid"),
        QString::number(QCoreApplication::applicationPid()),
        QStringLiteral("--ipc-session"),
        ipcSessionName_,
    });
    processUptime_.start();
    emit statusChanged(QStringLiteral("Starting isolated pet renderer"));
    process_.start();
}

void PetProcessSupervisor::handleFinished(int exitCode, QProcess::ExitStatus exitStatus) {
    terminateTimer_.stop();
    killTimer_.stop();
    if (stopping_) {
        if (relaunchAfterStop_) {
            relaunchAfterStop_ = false;
            if (replaceIpcSessionAfterStop_) {
                replaceIpcSessionAfterStop_ = false;
                if (!initializeIpcSession()) {
                    stopping_ = true;
                    return;
                }
            }
            stopping_ = false;
            launchNow();
            return;
        }
        emit statusChanged(QStringLiteral("Pet renderer stopped"));
        return;
    }
    const qint64 elapsed = processUptime_.isValid() ? processUptime_.elapsed() : 0;
    if (elapsed >= kStableRunMsec) {
        consecutiveFailures_ = 0;
    }
    emit statusChanged(
        QStringLiteral("Pet renderer exited (%1, code %2)")
            .arg(exitStatus == QProcess::CrashExit ? QStringLiteral("crash") : QStringLiteral("normal"))
            .arg(exitCode));
    scheduleRestart();
}

bool PetProcessSupervisor::initializeIpcSession() {
    ipcPollTimer_.stop();
    inboundQueue_.reset();
    reliableInboundQueue_.reset();
    broadcastQueue_.reset();
    controlQueue_.reset();

    const QString normalizedRoot = QDir(spec_.projectRoot).absolutePath();
    const QString rootDigest = QString::fromLatin1(
        QCryptographicHash::hash(normalizedRoot.toUtf8(), QCryptographicHash::Sha1)
            .toHex()
            .left(12));
    const QString random = QUuid::createUuid()
                               .toString(QUuid::WithoutBraces)
                               .remove(QLatin1Char('-'))
                               .left(8);
    ipcSessionName_ = QStringLiteral("BandoriPet-%1-%2-%3")
                          .arg(rootDigest)
                          .arg(QCoreApplication::applicationPid())
                          .arg(random);
    supervisorPeerId_ = QStringLiteral("main-%1-%2")
                            .arg(QCoreApplication::applicationPid())
                            .arg(random);

    inboundQueue_ = SharedMemoryLineQueue::create(
        makeSharedMemoryKey({ipcSessionName_, QStringLiteral("main-in")}));
    reliableInboundQueue_ = SharedMemoryLineQueue::create(
        makeSharedMemoryKey({ipcSessionName_, QStringLiteral("main-reliable-in")}),
        32,
        65'536,
        false);
    broadcastQueue_ = SharedMemoryLineQueue::create(
        makeSharedMemoryKey({ipcSessionName_, QStringLiteral("main-out")}));
    controlQueue_ = SharedMemoryLineQueue::create(
        makeSharedMemoryKey({ipcSessionName_, QStringLiteral("main-control")}),
        16,
        65'536,
        false);
    if (inboundQueue_ == nullptr || reliableInboundQueue_ == nullptr
        || broadcastQueue_ == nullptr || controlQueue_ == nullptr) {
        inboundQueue_.reset();
        reliableInboundQueue_.reset();
        broadcastQueue_.reset();
        controlQueue_.reset();
        emit statusChanged(QStringLiteral("Failed to create Rust-compatible IPC queues"));
        return false;
    }
    ipcPollTimer_.start();
    return true;
}

void PetProcessSupervisor::requestProcessStop() {
    const bool notified = controlQueue_ != nullptr
        && controlQueue_->publish(encodeIpcEnvelope(
            supervisorPeerId_, QStringLiteral("SHUTDOWN"), {}, {}, true));
    if (notified) {
        terminateTimer_.start(500);
        return;
    }
    process_.terminate();
    killTimer_.start(kTerminateGraceMsec);
}

void PetProcessSupervisor::pollIpcMessages() {
    if (reliableInboundQueue_ == nullptr) {
        return;
    }
    for (const QString& raw : reliableInboundQueue_->readAvailable()) {
        const QString line = decodeIpcEnvelopeLine(raw);
        if (line.startsWith(QStringLiteral("REGISTER\tPET\t"))) {
            emit statusChanged(QStringLiteral("Pet renderer registered on Rust IPC"));
        } else if (line.startsWith(QStringLiteral("UNREGISTER\tPET\t"))) {
            emit statusChanged(QStringLiteral("Pet renderer unregistered"));
        } else if (line.startsWith(QStringLiteral("PET_STATE\t"))) {
            const QByteArray configPath =
                QDir(spec_.projectRoot).filePath(QStringLiteral("config.json")).toUtf8();
            const QByteArray payload = line.mid(10).toUtf8();
            if (!bandori_config_save_pet_state(configPath.constData(), payload.constData())) {
                emit rendererLog(
                    QStringLiteral("Failed to persist pet state: %1")
                        .arg(QString::fromUtf8(bandori_config_last_error())));
            }
        }
    }
}

void PetProcessSupervisor::scheduleRestart() {
    if (stopping_ || restartTimer_.isActive()) {
        return;
    }
    if (consecutiveFailures_ >= kMaximumConsecutiveRestarts) {
        stopping_ = true;
        emit statusChanged(QStringLiteral("Pet renderer restart limit reached"));
        return;
    }
    const int delay = std::min(4'000, 250 * (1 << consecutiveFailures_));
    ++consecutiveFailures_;
    emit statusChanged(QStringLiteral("Restarting pet renderer in %1 ms").arg(delay));
    restartTimer_.start(delay);
}

QString PetProcessSupervisor::rendererProgram() const {
    const QString baseName = QStringLiteral("bandori-pet-renderer-rust");
    const QString sibling = QDir(QCoreApplication::applicationDirPath()).filePath(baseName);
    if (QFileInfo::exists(sibling)) {
        return sibling;
    }
#ifdef Q_OS_WIN
    const QString siblingExe = sibling + QStringLiteral(".exe");
    if (QFileInfo::exists(siblingExe)) {
        return siblingExe;
    }
#endif
#ifdef Q_OS_MACOS
    QDir bundleRoot(QCoreApplication::applicationDirPath());
    if (bundleRoot.cdUp() && bundleRoot.cdUp() && bundleRoot.cdUp()) {
        const QString bundledHelper = bundleRoot.filePath(
            baseName + QStringLiteral(".app/Contents/MacOS/") + baseName);
        if (QFileInfo::exists(bundledHelper)) {
            return bundledHelper;
        }
    }
#endif
    return QStandardPaths::findExecutable(baseName);
}

} // namespace bandori
