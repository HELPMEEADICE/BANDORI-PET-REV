#include "live2d_gl_widget.h"
#include "pet_ipc_client.h"

#include <QApplication>
#include <QCommandLineOption>
#include <QCommandLineParser>
#include <QDir>
#include <QFileInfo>
#include <QHash>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPoint>
#include <QSet>
#include <QStandardPaths>
#include <QStringList>
#include <QTimer>
#include <QUuid>

#include <algorithm>
#include <limits>

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

bool optionBool(const QString& value, bool fallback = false) {
    const QString normalized = value.trimmed().toLower();
    if (normalized == QStringLiteral("1") || normalized == QStringLiteral("true")
        || normalized == QStringLiteral("yes") || normalized == QStringLiteral("on")) {
        return true;
    }
    if (normalized == QStringLiteral("0") || normalized == QStringLiteral("false")
        || normalized == QStringLiteral("no") || normalized == QStringLiteral("off")) {
        return false;
    }
    return fallback;
}

QJsonObject ipcJsonPayload(const QString& line) {
    const qsizetype separator = line.indexOf(u'\t');
    if (separator < 0) {
        return {};
    }
    const QJsonDocument document = QJsonDocument::fromJson(line.mid(separator + 1).toUtf8());
    return document.isObject() ? document.object() : QJsonObject {};
}

QString compactJson(const QJsonObject& value) {
    return QString::fromUtf8(QJsonDocument(value).toJson(QJsonDocument::Compact));
}

struct PeerDragState {
    QString dragId;
    QPoint origin;
};

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
    QCommandLineOption hitAlphaThreshold(
        QStringLiteral("hit-alpha-threshold"),
        QStringLiteral("Alpha threshold used for transparent input passthrough"),
        QStringLiteral("alpha"),
        QStringLiteral("8"));
    QCommandLineOption dragLocked(
        QStringLiteral("drag-locked"),
        QStringLiteral("Whether direct pet-window dragging is locked"),
        QStringLiteral("bool"),
        QStringLiteral("false"));
    QCommandLineOption moveAllRolesTogether(
        QStringLiteral("move-all-roles-together"),
        QStringLiteral("Mirror drag sessions across all active pet processes"),
        QStringLiteral("bool"),
        QStringLiteral("false"));
    QCommandLineOption headTrackingEnabled(
        QStringLiteral("head-tracking-enabled"),
        QStringLiteral("Track the global mouse cursor when mutual gaze is disabled"),
        QStringLiteral("bool"),
        QStringLiteral("true"));
    QCommandLineOption mutualGazeEnabled(
        QStringLiteral("mutual-gaze-enabled"),
        QStringLiteral("Look toward the nearest active pet process"),
        QStringLiteral("bool"),
        QStringLiteral("false"));
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
         hitAlphaThreshold,
         dragLocked,
         moveAllRolesTogether,
         headTrackingEnabled,
         mutualGazeEnabled,
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
    widget.setHitAlphaThreshold(parser.value(hitAlphaThreshold).toInt());
    widget.setDragLocked(optionBool(parser.value(dragLocked)));
    bool headTracking = optionBool(parser.value(headTrackingEnabled), true);
    bool mutualGaze = optionBool(parser.value(mutualGazeEnabled));
    widget.setHeadTrackingEnabled(headTracking && !mutualGaze);
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
    bool moveAllRoles = optionBool(parser.value(moveAllRolesTogether));
    QString activeDragId;
    QHash<QString, PeerDragState> peerDragStates;
    QSet<QString> completedPeerDragIds;
    QStringList completedPeerDragOrder;
    QHash<QString, QPoint> peerPositions;
    QPoint lastPublishedCenter;
    bool lastPublishedCenterValid = false;
    auto updateMutualGaze = [&widget, &mutualGaze, &peerPositions]() {
        if (!mutualGaze || peerPositions.isEmpty()) {
            widget.clearGazeTarget();
            return;
        }
        const QPoint ownCenter = widget.geometry().center();
        QPoint nearest;
        qint64 nearestDistance = std::numeric_limits<qint64>::max();
        for (auto iterator = peerPositions.cbegin(); iterator != peerPositions.cend(); ++iterator) {
            const qint64 dx = static_cast<qint64>(iterator.value().x()) - ownCenter.x();
            const qint64 dy = static_cast<qint64>(iterator.value().y()) - ownCenter.y();
            const qint64 distance = dx * dx + dy * dy;
            if (distance < nearestDistance) {
                nearestDistance = distance;
                nearest = iterator.value();
            }
        }
        widget.setGazeTargetGlobal(nearest);
    };
    QTimer peerPositionTimer;
    peerPositionTimer.setInterval(200);
    QObject::connect(
        &peerPositionTimer,
        &QTimer::timeout,
        ipcClient,
        [ipcClient,
         &widget,
         &mutualGaze,
         &lastPublishedCenter,
         &lastPublishedCenterValid,
         characterId]() {
            if (!mutualGaze) {
                return;
            }
            const QPoint center = widget.geometry().center();
            if (lastPublishedCenterValid && center == lastPublishedCenter) {
                return;
            }
            if (ipcClient->publishLine(
                    QStringLiteral("PEER_POS\t")
                    + compactJson({
                        {QStringLiteral("character"), characterId},
                        {QStringLiteral("x"), center.x()},
                        {QStringLiteral("y"), center.y()},
                    }))) {
                lastPublishedCenter = center;
                lastPublishedCenterValid = true;
            }
        });
    peerPositionTimer.start();
    QObject::connect(
        &widget,
        &bandori::Live2dGlWidget::windowDragStarted,
        ipcClient,
        [&activeDragId]() {
            activeDragId = QUuid::createUuid()
                               .toString(QUuid::WithoutBraces)
                               .remove(QLatin1Char('-'));
        });
    QObject::connect(
        &widget,
        &bandori::Live2dGlWidget::windowDragMoved,
        ipcClient,
        [ipcClient, &moveAllRoles, &activeDragId, characterId](int totalDx, int totalDy) {
            if (!moveAllRoles || activeDragId.isEmpty()) {
                return;
            }
            ipcClient->publishLine(
                QStringLiteral("PEER_DRAG\t")
                + compactJson({
                    {QStringLiteral("character"), characterId},
                    {QStringLiteral("drag_id"), activeDragId},
                    {QStringLiteral("total_dx"), totalDx},
                    {QStringLiteral("total_dy"), totalDy},
                }));
        });
    QObject::connect(
        &widget,
        &bandori::Live2dGlWidget::windowDragFinished,
        ipcClient,
        [ipcClient, &moveAllRoles, &activeDragId, characterId](int totalDx, int totalDy) {
            if (moveAllRoles && !activeDragId.isEmpty() && (totalDx != 0 || totalDy != 0)) {
                ipcClient->publishLine(
                    QStringLiteral("PEER_DRAG_END\t")
                        + compactJson({
                            {QStringLiteral("character"), characterId},
                            {QStringLiteral("drag_id"), activeDragId},
                            {QStringLiteral("total_dx"), totalDx},
                            {QStringLiteral("total_dy"), totalDy},
                        }),
                    true);
            }
            activeDragId.clear();
        });
    QObject::connect(
        ipcClient, &bandori::PetIpcClient::shutdownRequested, &app, &QCoreApplication::quit);
    QObject::connect(
        ipcClient,
        &bandori::PetIpcClient::controlLineReceived,
        &widget,
        [&widget,
         characterId,
         &moveAllRoles,
         &peerDragStates,
         &completedPeerDragIds,
         &completedPeerDragOrder,
         &headTracking,
         &mutualGaze,
         &peerPositions,
         &lastPublishedCenterValid,
         &updateMutualGaze](const QString& line) {
            const bool peerDragFinished = line.startsWith(QStringLiteral("PEER_DRAG_END\t"));
            if (peerDragFinished || line.startsWith(QStringLiteral("PEER_DRAG\t"))) {
                if (!moveAllRoles) {
                    return;
                }
                const QJsonObject payload = ipcJsonPayload(line);
                const QString peerCharacter = payload.value(QStringLiteral("character")).toString();
                if (peerCharacter.isEmpty() || peerCharacter == characterId) {
                    return;
                }
                const QString dragId = payload.value(QStringLiteral("drag_id")).toString().trimmed();
                QPoint target;
                if (!dragId.isEmpty()) {
                    if (completedPeerDragIds.contains(dragId)) {
                        return;
                    }
                    auto state = peerDragStates.value(peerCharacter);
                    if (state.dragId != dragId) {
                        state = {dragId, widget.pos()};
                        peerDragStates.insert(peerCharacter, state);
                    }
                    target = state.origin
                        + QPoint(
                            payload.value(QStringLiteral("total_dx")).toInt(),
                            payload.value(QStringLiteral("total_dy")).toInt());
                } else {
                    target = widget.pos()
                        + QPoint(
                            payload.value(QStringLiteral("dx")).toInt(),
                            payload.value(QStringLiteral("dy")).toInt());
                }
                widget.move(target);
                if (peerDragFinished && !dragId.isEmpty()) {
                    peerDragStates.remove(peerCharacter);
                    completedPeerDragIds.insert(dragId);
                    completedPeerDragOrder.append(dragId);
                    while (completedPeerDragOrder.size() > 128) {
                        completedPeerDragIds.remove(completedPeerDragOrder.takeFirst());
                    }
                }
                return;
            }
            if (line.startsWith(QStringLiteral("PEER_OFFLINE\t"))) {
                const QString peerCharacter =
                    ipcJsonPayload(line).value(QStringLiteral("character")).toString();
                if (!peerCharacter.isEmpty()) {
                    peerDragStates.remove(peerCharacter);
                    peerPositions.remove(peerCharacter);
                    updateMutualGaze();
                }
                return;
            }
            if (line.startsWith(QStringLiteral("PEER_POS\t"))) {
                const QJsonObject payload = ipcJsonPayload(line);
                const QString peerCharacter = payload.value(QStringLiteral("character")).toString();
                if (!peerCharacter.isEmpty() && peerCharacter != characterId) {
                    peerPositions.insert(
                        peerCharacter,
                        QPoint(
                            payload.value(QStringLiteral("x")).toInt(),
                            payload.value(QStringLiteral("y")).toInt()));
                    updateMutualGaze();
                }
                return;
            }
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
            if (settings.contains(QStringLiteral("live2d_hit_alpha_threshold"))) {
                widget.setHitAlphaThreshold(
                    settings.value(QStringLiteral("live2d_hit_alpha_threshold")).toInt(8));
            }
            if (settings.contains(QStringLiteral("drag_locked"))) {
                widget.setDragLocked(settings.value(QStringLiteral("drag_locked")).toBool(false));
            }
            if (settings.contains(QStringLiteral("move_all_roles_together"))) {
                moveAllRoles =
                    settings.value(QStringLiteral("move_all_roles_together")).toBool(false);
                if (!moveAllRoles) {
                    peerDragStates.clear();
                }
            }
            if (settings.contains(QStringLiteral("live2d_head_tracking_enabled"))) {
                headTracking =
                    settings.value(QStringLiteral("live2d_head_tracking_enabled")).toBool(true);
            }
            if (settings.contains(QStringLiteral("live2d_mutual_gaze_enabled"))) {
                mutualGaze =
                    settings.value(QStringLiteral("live2d_mutual_gaze_enabled")).toBool(false);
                lastPublishedCenterValid = false;
            }
            widget.setHeadTrackingEnabled(headTracking && !mutualGaze);
            updateMutualGaze();
        });
    QObject::connect(&app, &QCoreApplication::aboutToQuit, ipcClient, &bandori::PetIpcClient::stop);
    ipcClient->start();
    widget.show();
    return app.exec();
}
