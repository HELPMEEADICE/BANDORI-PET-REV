#include "live2d_gl_widget.h"
#include "pet_ipc_client.h"

#include <QApplication>
#include <QCommandLineOption>
#include <QCommandLineParser>
#include <QDir>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QStandardPaths>
#include <QStringList>
#include <QTimer>

#include <algorithm>

#ifdef Q_OS_WIN
#define NOMINMAX
#include <windows.h>
#else
#include <cerrno>
#include <csignal>
#endif

namespace {

bool isProcessAlive(qint64 processId) {
    if (processId <= 0) {
        return true;
    }
#ifdef Q_OS_WIN
    const HANDLE process = OpenProcess(SYNCHRONIZE, FALSE, static_cast<DWORD>(processId));
    if (process == nullptr) {
        return false;
    }
    const bool alive = WaitForSingleObject(process, 0) == WAIT_TIMEOUT;
    CloseHandle(process);
    return alive;
#else
    const int result = kill(static_cast<pid_t>(processId), 0);
    return result == 0 || errno == EPERM;
#endif
}

} // namespace

int main(int argc, char* argv[]) {
    bandori::Live2dGlWidget::configureDefaultSurfaceFormat(true);
    QApplication app(argc, argv);
    QApplication::setApplicationName(QStringLiteral("BandoriPetRenderer"));
    QApplication::setOrganizationName(QStringLiteral("BandoriPet"));
    QApplication::setQuitOnLastWindowClosed(true);

    QCommandLineParser parser;
    parser.setApplicationDescription(QStringLiteral("Isolated Rust + LuaJIT Live2D pet renderer"));
    parser.addHelpOption();
    QCommandLineOption projectRoot(
        QStringLiteral("project-root"),
        QStringLiteral("BandoriPet installation root"),
        QStringLiteral("path"),
        QDir::currentPath());
    QCommandLineOption userModels(
        QStringLiteral("user-models"),
        QStringLiteral("Writable user model directory"),
        QStringLiteral("path"),
        QStandardPaths::writableLocation(QStandardPaths::AppDataLocation) + QStringLiteral("/models"));
    QCommandLineOption model(
        QStringLiteral("model"),
        QStringLiteral("Model manifest path"),
        QStringLiteral("path"));
    QCommandLineOption character(
        QStringLiteral("character"),
        QStringLiteral("Character identifier used for IPC registration"),
        QStringLiteral("id"));
    QCommandLineOption format(
        QStringLiteral("format"),
        QStringLiteral("Model format: moc or moc3"),
        QStringLiteral("format"),
        QStringLiteral("moc3"));
    QCommandLineOption width(
        QStringLiteral("width"), QStringLiteral("Pet width"), QStringLiteral("pixels"), QStringLiteral("400"));
    QCommandLineOption height(
        QStringLiteral("height"), QStringLiteral("Pet height"), QStringLiteral("pixels"), QStringLiteral("650"));
    QCommandLineOption fps(
        QStringLiteral("fps"), QStringLiteral("Render frame rate"), QStringLiteral("fps"), QStringLiteral("120"));
    QCommandLineOption opacity(
        QStringLiteral("opacity"),
        QStringLiteral("Window opacity"),
        QStringLiteral("opacity"),
        QStringLiteral("1.0"));
    QCommandLineOption lipSyncMaxOpen(
        QStringLiteral("lip-sync-max-open"),
        QStringLiteral("Maximum mouth-open parameter used by lip sync"),
        QStringLiteral("value"),
        QStringLiteral("0.55"));
    QCommandLineOption parentPid(
        QStringLiteral("parent-pid"),
        QStringLiteral("Quit when this supervisor process exits"),
        QStringLiteral("pid"),
        QStringLiteral("0"));
    QCommandLineOption ipcSession(
        QStringLiteral("ipc-session"),
        QStringLiteral("Bandori shared-memory IPC session name"),
        QStringLiteral("name"));
    parser.addOptions(
        {projectRoot,
         userModels,
         model,
         character,
         format,
         width,
         height,
         fps,
         opacity,
         lipSyncMaxOpen,
         parentPid,
         ipcSession});
    parser.process(app);

    if (!parser.isSet(model)) {
        parser.showHelp(2);
    }
    const auto modelFormat = parser.value(format).compare(QStringLiteral("moc"), Qt::CaseInsensitive) == 0
        ? bandori::Live2dGlWidget::ModelFormat::Moc
        : bandori::Live2dGlWidget::ModelFormat::Moc3;
    bandori::Live2dGlWidget widget(
        parser.value(projectRoot),
        parser.value(userModels),
        parser.value(model),
        modelFormat);
    widget.setFramesPerSecond(parser.value(fps).toInt());
    widget.setLipSyncMaxOpen(parser.value(lipSyncMaxOpen).toDouble());
    widget.setWindowOpacity(std::clamp(parser.value(opacity).toDouble(), 0.05, 1.0));
    widget.setWindowFlags(Qt::Tool | Qt::FramelessWindowHint | Qt::WindowStaysOnTopHint);
    widget.setAttribute(Qt::WA_TranslucentBackground, true);
    widget.resize(std::max(parser.value(width).toInt(), 1), std::max(parser.value(height).toInt(), 1));

    QTimer parentWatch;
    const qint64 supervisorPid = parser.value(parentPid).toLongLong();
    if (supervisorPid > 0) {
        parentWatch.setInterval(1'000);
        QObject::connect(&parentWatch, &QTimer::timeout, &app, [&app, supervisorPid]() {
            if (!isProcessAlive(supervisorPid)) {
                app.quit();
            }
        });
        parentWatch.start();
    }

    QString characterId = parser.value(character).trimmed();
    if (characterId.isEmpty()) {
        characterId = QFileInfo(parser.value(model)).completeBaseName();
    }
    QString ipcSessionName = parser.value(ipcSession).trimmed();
    if (ipcSessionName.isEmpty()) {
        ipcSessionName = qEnvironmentVariable("BANDORI_PET_IPC_SERVER_NAME").trimmed();
    }
    auto* ipcClient = new bandori::PetIpcClient(ipcSessionName, characterId, &app);
    QObject::connect(
        ipcClient, &bandori::PetIpcClient::shutdownRequested, &app, &QCoreApplication::quit);
    QObject::connect(
        ipcClient,
        &bandori::PetIpcClient::controlLineReceived,
        &widget,
        [&widget, characterId](const QString& line) {
            if (line.startsWith(QStringLiteral("ACTION\t"))) {
                const QStringList parts = line.split(u'\t');
                if (parts.size() >= 3 && parts.at(1) == characterId) {
                    widget.triggerAction(parts.mid(2).join(u'\t'), characterId);
                } else if (parts.size() == 2) {
                    widget.triggerAction(parts.at(1), characterId);
                }
                return;
            }
            if (line.startsWith(QStringLiteral("LIP\t"))) {
                const QStringList parts = line.split(u'\t');
                if (parts.size() < 3 || parts.at(1) != characterId) {
                    return;
                }
                bool levelValid = false;
                bool formValid = true;
                const double level = parts.at(2).toDouble(&levelValid);
                const double form = parts.size() >= 4 ? parts.at(3).toDouble(&formValid) : 0.0;
                if (levelValid && formValid) {
                    widget.setLipSyncPose(level, form);
                }
                return;
            }
            if (!line.startsWith(QStringLiteral("SETTINGS\t"))) {
                return;
            }
            const QByteArray payload = line.mid(9).toUtf8();
            const QJsonDocument document = QJsonDocument::fromJson(payload);
            if (!document.isObject()) {
                return;
            }
            const QJsonObject settings = document.object();
            if (settings.contains(QStringLiteral("fps"))) {
                widget.setFramesPerSecond(settings.value(QStringLiteral("fps")).toInt(120));
            }
            if (settings.contains(QStringLiteral("opacity"))) {
                widget.setWindowOpacity(std::clamp(
                    settings.value(QStringLiteral("opacity")).toDouble(1.0), 0.05, 1.0));
            }
            if (settings.contains(QStringLiteral("live2d_lip_sync_max_open"))) {
                widget.setLipSyncMaxOpen(
                    settings.value(QStringLiteral("live2d_lip_sync_max_open")).toDouble(0.55));
            }
        });
    QObject::connect(&app, &QCoreApplication::aboutToQuit, ipcClient, &bandori::PetIpcClient::stop);
    ipcClient->start();
    widget.show();
    return app.exec();
}
