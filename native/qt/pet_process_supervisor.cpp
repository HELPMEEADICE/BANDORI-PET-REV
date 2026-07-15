#include "pet_process_supervisor.h"

#include "bandori_config_ffi.h"
#include "shared_memory_line_queue.h"

#include <QByteArray>
#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDir>
#include <QElapsedTimer>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
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

QString petName(const PetLaunchSpec& spec) {
    if (!spec.character.isEmpty()) {
        return spec.character;
    }
    return QFileInfo(spec.modelPath).completeBaseName();
}

PetLaunchSpec normalizedSpec(PetLaunchSpec spec) {
    spec.projectRoot = QDir(spec.projectRoot).absolutePath();
    spec.userModelsRoot = QDir(spec.userModelsRoot).absolutePath();
    spec.width = std::max(spec.width, 1);
    spec.height = std::max(spec.height, 1);
    spec.fps = std::clamp(spec.fps, 10, 240);
    spec.opacity = std::clamp(spec.opacity, 0.05, 1.0);
    spec.live2dQuality =
        spec.live2dQuality.trimmed().compare(QStringLiteral("performance"), Qt::CaseInsensitive) == 0
        ? QStringLiteral("performance")
        : QStringLiteral("balanced");
    spec.live2dScale = std::clamp(spec.live2dScale, 25, 500);
    spec.lipSyncMaxOpen = std::clamp(spec.lipSyncMaxOpen, 0.0, 1.0);
    spec.hitAlphaThreshold = std::clamp(spec.hitAlphaThreshold, 0, 255);
    return spec;
}
}  // namespace

struct PetProcessSupervisor::ChildState {
    explicit ChildState(PetLaunchSpec launchSpec)
        : spec(std::move(launchSpec)) {
        process.setProcessChannelMode(QProcess::SeparateChannels);
        restartTimer.setSingleShot(true);
        terminateTimer.setSingleShot(true);
        killTimer.setSingleShot(true);
    }

    PetLaunchSpec spec;
    QProcess process;
    QTimer restartTimer;
    QTimer terminateTimer;
    QTimer killTimer;
    QElapsedTimer uptime;
    int consecutiveFailures = 0;
};

PetProcessSupervisor::PetProcessSupervisor(QObject* parent)
    : QObject(parent) {
    ipcPollTimer_.setInterval(30);
    connect(&ipcPollTimer_, &QTimer::timeout, this, &PetProcessSupervisor::pollIpcMessages);
}

PetProcessSupervisor::~PetProcessSupervisor() {
    stop();
    for (const auto& child : children_) {
        child->process.disconnect(this);
        if (child->process.state() != QProcess::NotRunning) {
            child->process.kill();
            child->process.waitForFinished(1'000);
        }
    }
    children_.clear();
    resetIpcSession();
}

void PetProcessSupervisor::start(PetLaunchSpec spec) {
    startAll({std::move(spec)});
}

void PetProcessSupervisor::startAll(QList<PetLaunchSpec> specs) {
    QList<PetLaunchSpec> normalized;
    QString projectRoot;
    for (PetLaunchSpec& spec : specs) {
        if (spec.modelPath.trimmed().isEmpty()) {
            continue;
        }
        PetLaunchSpec value = normalizedSpec(std::move(spec));
        if (projectRoot.isEmpty()) {
            projectRoot = value.projectRoot;
        } else if (value.projectRoot != projectRoot) {
            emit statusChanged(QStringLiteral("All pet renderers must share one project root"));
            return;
        }
        normalized.append(std::move(value));
    }
    if (normalized.isEmpty()) {
        stop();
        return;
    }

    pendingSpecs_ = std::move(normalized);
    if (!children_.empty()) {
        stopping_ = true;
        relaunchAfterStop_ = true;
        emit statusChanged(
            QStringLiteral("Replacing %1 pet renderer(s)").arg(children_.size()));
        requestFleetStop();
        return;
    }
    launchPendingFleet();
}

void PetProcessSupervisor::stop() {
    pendingSpecs_.clear();
    relaunchAfterStop_ = false;
    stopping_ = true;
    if (children_.empty()) {
        resetIpcSession();
        return;
    }
    emit statusChanged(
        QStringLiteral("Stopping %1 pet renderer(s)").arg(children_.size()));
    requestFleetStop();
}

bool PetProcessSupervisor::broadcastSettings(const QString& settingsJson) {
    if (settingsJson.trimmed().isEmpty()) {
        return false;
    }
    return broadcastControlLine(QStringLiteral("SETTINGS\t") + settingsJson);
}

bool PetProcessSupervisor::broadcastControlLine(const QString& line, bool reliable) {
    SharedMemoryLineQueue* queue = reliable ? controlQueue_.get() : broadcastQueue_.get();
    if (queue == nullptr || line.trimmed().isEmpty()) {
        return false;
    }
    return queue->publish(
        encodeIpcEnvelope(supervisorPeerId_, line, {}, {}, reliable));
}

bool PetProcessSupervisor::isRunning() const {
    return std::any_of(children_.cbegin(), children_.cend(), [](const auto& child) {
        return child->process.state() != QProcess::NotRunning
            || child->restartTimer.isActive();
    });
}

int PetProcessSupervisor::runningCount() const {
    return static_cast<int>(std::count_if(
        children_.cbegin(), children_.cend(), [](const auto& child) {
            return child->process.state() != QProcess::NotRunning;
        }));
}

int PetProcessSupervisor::targetCount() const {
    if (relaunchAfterStop_ && !pendingSpecs_.isEmpty()) {
        return pendingSpecs_.size();
    }
    return static_cast<int>(children_.size());
}

void PetProcessSupervisor::launchPendingFleet() {
    if (pendingSpecs_.isEmpty()) {
        return;
    }
    QList<PetLaunchSpec> specs = std::move(pendingSpecs_);
    pendingSpecs_.clear();
    projectRoot_ = specs.first().projectRoot;
    if (!initializeIpcSession()) {
        stopping_ = true;
        return;
    }

    stopping_ = false;
    relaunchAfterStop_ = false;
    children_.reserve(static_cast<std::size_t>(specs.size()));
    for (PetLaunchSpec& spec : specs) {
        auto state = std::make_unique<ChildState>(std::move(spec));
        ChildState* child = state.get();
        children_.push_back(std::move(state));

        connect(&child->restartTimer, &QTimer::timeout, this, [this, child]() {
            launchNow(child);
        });
        connect(&child->terminateTimer, &QTimer::timeout, this, [this, child]() {
            if (child->process.state() != QProcess::NotRunning) {
                child->process.terminate();
                child->killTimer.start(kTerminateGraceMsec);
            }
        });
        connect(&child->killTimer, &QTimer::timeout, this, [this, child]() {
            if (child->process.state() != QProcess::NotRunning) {
                emit statusChanged(
                    QStringLiteral("Pet renderer %1 did not stop; killing it")
                        .arg(petName(child->spec)));
                child->process.kill();
            }
        });
        connect(
            &child->process,
            QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished),
            this,
            [this, child](int exitCode, QProcess::ExitStatus exitStatus) {
                handleFinished(child, exitCode, static_cast<int>(exitStatus));
            });
        connect(&child->process, &QProcess::readyReadStandardError, this, [this, child]() {
            const QString message =
                QString::fromUtf8(child->process.readAllStandardError()).trimmed();
            if (!message.isEmpty()) {
                emit rendererLog(
                    QStringLiteral("[%1] %2").arg(petName(child->spec), message));
            }
        });
        connect(
            &child->process,
            &QProcess::errorOccurred,
            this,
            [this, child](QProcess::ProcessError error) {
                if (error == QProcess::FailedToStart) {
                    emit statusChanged(
                        QStringLiteral("Failed to start pet renderer %1: %2")
                            .arg(petName(child->spec), child->process.errorString()));
                    scheduleRestart(child);
                }
            });
    }

    for (const auto& child : children_) {
        launchNow(child.get());
    }
    emit statusChanged(
        QStringLiteral("Starting %1 isolated pet renderer(s) on shared IPC")
            .arg(children_.size()));
}

void PetProcessSupervisor::launchNow(ChildState* child) {
    if (stopping_ || child == nullptr || child->process.state() != QProcess::NotRunning) {
        return;
    }
    child->restartTimer.stop();
    child->terminateTimer.stop();
    child->killTimer.stop();
    const QString program = rendererProgram();
    if (program.isEmpty()) {
        emit statusChanged(QStringLiteral("Pet renderer executable was not found"));
        scheduleRestart(child);
        return;
    }

    const PetLaunchSpec& spec = child->spec;
    child->process.setProgram(program);
    child->process.setWorkingDirectory(spec.projectRoot);
    QProcessEnvironment environment = QProcessEnvironment::systemEnvironment();
    environment.insert(QStringLiteral("BANDORI_PET_IPC_SERVER_NAME"), ipcSessionName_);
    child->process.setProcessEnvironment(environment);
    child->process.setArguments({
        QStringLiteral("--project-root"),
        spec.projectRoot,
        QStringLiteral("--user-models"),
        spec.userModelsRoot,
        QStringLiteral("--model"),
        spec.modelPath,
        QStringLiteral("--character"),
        spec.character,
        QStringLiteral("--language"),
        spec.language,
        QStringLiteral("--format"),
        spec.format,
        QStringLiteral("--width"),
        QString::number(spec.width),
        QStringLiteral("--height"),
        QString::number(spec.height),
        QStringLiteral("--x"),
        QString::number(spec.x),
        QStringLiteral("--y"),
        QString::number(spec.y),
        QStringLiteral("--fps"),
        QString::number(spec.fps),
        QStringLiteral("--opacity"),
        QString::number(spec.opacity, 'f', 3),
        QStringLiteral("--vsync"),
        spec.vsync ? QStringLiteral("true") : QStringLiteral("false"),
        QStringLiteral("--quality"),
        spec.live2dQuality,
        QStringLiteral("--scale"),
        QString::number(spec.live2dScale),
        QStringLiteral("--lip-sync-max-open"),
        QString::number(spec.lipSyncMaxOpen, 'f', 3),
        QStringLiteral("--hit-alpha-threshold"),
        QString::number(spec.hitAlphaThreshold),
        QStringLiteral("--click-motion-actions"),
        spec.clickMotionActions,
        QStringLiteral("--poke-motion"),
        spec.pokeMotion,
        QStringLiteral("--poke-expression"),
        spec.pokeExpression,
        QStringLiteral("--default-motion"),
        spec.defaultMotion,
        QStringLiteral("--default-expression"),
        spec.defaultExpression,
        QStringLiteral("--idle-actions-enabled"),
        spec.idleActionsEnabled ? QStringLiteral("true") : QStringLiteral("false"),
        QStringLiteral("--random-actions-enabled"),
        spec.randomActionsEnabled ? QStringLiteral("true") : QStringLiteral("false"),
        QStringLiteral("--drag-locked"),
        spec.dragLocked ? QStringLiteral("true") : QStringLiteral("false"),
        QStringLiteral("--move-all-roles-together"),
        spec.moveAllRolesTogether ? QStringLiteral("true") : QStringLiteral("false"),
        QStringLiteral("--head-tracking-enabled"),
        spec.headTrackingEnabled ? QStringLiteral("true") : QStringLiteral("false"),
        QStringLiteral("--mutual-gaze-enabled"),
        spec.mutualGazeEnabled ? QStringLiteral("true") : QStringLiteral("false"),
        QStringLiteral("--parent-pid"),
        QString::number(QCoreApplication::applicationPid()),
        QStringLiteral("--ipc-session"),
        ipcSessionName_,
    });
    child->uptime.start();
    child->process.start();
}

void PetProcessSupervisor::handleFinished(
    ChildState* child,
    int exitCode,
    int exitStatus) {
    if (child == nullptr) {
        return;
    }
    child->terminateTimer.stop();
    child->killTimer.stop();
    publishPeerOffline(child->spec.character);
    if (stopping_) {
        finalizeStoppedFleet();
        return;
    }
    const qint64 elapsed = child->uptime.isValid() ? child->uptime.elapsed() : 0;
    if (elapsed >= kStableRunMsec) {
        child->consecutiveFailures = 0;
    }
    emit statusChanged(
        QStringLiteral("Pet renderer %1 exited (%2, code %3)")
            .arg(
                petName(child->spec),
                exitStatus == static_cast<int>(QProcess::CrashExit)
                    ? QStringLiteral("crash")
                    : QStringLiteral("normal"))
            .arg(exitCode));
    scheduleRestart(child);
}

void PetProcessSupervisor::scheduleRestart(ChildState* child) {
    if (stopping_ || child == nullptr || child->restartTimer.isActive()) {
        return;
    }
    if (child->consecutiveFailures >= kMaximumConsecutiveRestarts) {
        emit statusChanged(
            QStringLiteral("Pet renderer %1 reached its restart limit")
                .arg(petName(child->spec)));
        return;
    }
    const int delay = std::min(4'000, 250 * (1 << child->consecutiveFailures));
    ++child->consecutiveFailures;
    emit statusChanged(
        QStringLiteral("Restarting pet renderer %1 in %2 ms")
            .arg(petName(child->spec))
            .arg(delay));
    child->restartTimer.start(delay);
}

bool PetProcessSupervisor::initializeIpcSession() {
    resetIpcSession();
    const QString rootDigest = QString::fromLatin1(
        QCryptographicHash::hash(projectRoot_.toUtf8(), QCryptographicHash::Sha1)
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
        resetIpcSession();
        emit statusChanged(QStringLiteral("Failed to create Rust-compatible IPC queues"));
        return false;
    }
    ipcPollTimer_.start();
    return true;
}

void PetProcessSupervisor::resetIpcSession() {
    ipcPollTimer_.stop();
    inboundQueue_.reset();
    reliableInboundQueue_.reset();
    broadcastQueue_.reset();
    controlQueue_.reset();
    ipcSessionName_.clear();
    supervisorPeerId_.clear();
}

void PetProcessSupervisor::requestFleetStop() {
    for (const auto& child : children_) {
        child->restartTimer.stop();
    }
    const bool notified = controlQueue_ != nullptr
        && controlQueue_->publish(encodeIpcEnvelope(
            supervisorPeerId_, QStringLiteral("SHUTDOWN"), {}, {}, true));
    for (const auto& child : children_) {
        if (child->process.state() == QProcess::NotRunning) {
            continue;
        }
        if (notified) {
            child->terminateTimer.start(500);
        } else {
            child->process.terminate();
            child->killTimer.start(kTerminateGraceMsec);
        }
    }
    finalizeStoppedFleet();
}

void PetProcessSupervisor::finalizeStoppedFleet() {
    if (finalizeScheduled_) {
        return;
    }
    const bool anyRunning = std::any_of(
        children_.cbegin(), children_.cend(), [](const auto& child) {
            return child->process.state() != QProcess::NotRunning;
        });
    if (anyRunning) {
        return;
    }
    finalizeScheduled_ = true;
    QTimer::singleShot(0, this, [this]() {
        finalizeScheduled_ = false;
        if (std::any_of(children_.cbegin(), children_.cend(), [](const auto& child) {
                return child->process.state() != QProcess::NotRunning;
            })) {
            return;
        }
        children_.clear();
        resetIpcSession();
        if (relaunchAfterStop_ && !pendingSpecs_.isEmpty()) {
            relaunchAfterStop_ = false;
            launchPendingFleet();
            return;
        }
        stopping_ = true;
        emit statusChanged(QStringLiteral("All pet renderers stopped"));
    });
}

void PetProcessSupervisor::publishPeerOffline(const QString& character) {
    if (character.isEmpty() || controlQueue_ == nullptr) {
        return;
    }
    const QString payload = QString::fromUtf8(
        QJsonDocument(QJsonObject {{QStringLiteral("character"), character}})
            .toJson(QJsonDocument::Compact));
    controlQueue_->publish(encodeIpcEnvelope(
        supervisorPeerId_,
        QStringLiteral("PEER_OFFLINE\t") + payload,
        {},
        {},
        true));
}

void PetProcessSupervisor::pollIpcMessages() {
    if (inboundQueue_ == nullptr || reliableInboundQueue_ == nullptr
        || broadcastQueue_ == nullptr || controlQueue_ == nullptr) {
        return;
    }
    for (const QString& raw : inboundQueue_->readAvailable()) {
        broadcastQueue_->publish(raw);
    }
    for (const QString& raw : reliableInboundQueue_->readAvailable()) {
        const QString line = decodeIpcEnvelopeLine(raw);
        if (line.startsWith(QStringLiteral("REGISTER\tPET\t"))) {
            emit statusChanged(
                QStringLiteral("Pet %1 registered on shared Rust IPC")
                    .arg(line.section(QLatin1Char('\t'), 2, 2)));
        } else if (line.startsWith(QStringLiteral("UNREGISTER\tPET\t"))) {
            const QString character = line.section(QLatin1Char('\t'), 2, 2);
            emit statusChanged(
                QStringLiteral("Pet %1 unregistered")
                    .arg(character));
            publishPeerOffline(character);
        } else if (line.startsWith(QStringLiteral("PET_STATE\t"))) {
            const QByteArray configPath =
                QDir(projectRoot_).filePath(QStringLiteral("config.json")).toUtf8();
            const QByteArray payload = line.mid(10).toUtf8();
            if (!bandori_config_save_pet_state(configPath.constData(), payload.constData())) {
                emit rendererLog(
                    QStringLiteral("Failed to persist pet state: %1")
                        .arg(QString::fromUtf8(bandori_config_last_error())));
            }
        } else {
            controlQueue_->publish(raw);
            emit controlRequest(line);
        }
    }
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

}  // namespace bandori
