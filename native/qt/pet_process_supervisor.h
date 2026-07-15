#pragma once

#include <QObject>
#include <QList>
#include <QString>
#include <QTimer>

#include <memory>
#include <vector>

namespace bandori {

class SharedMemoryLineQueue;

struct PetLaunchSpec {
    QString projectRoot;
    QString userModelsRoot;
    QString modelPath;
    QString character;
    QString language;
    QString format = QStringLiteral("moc3");
    int width = 400;
    int height = 650;
    int x = -1;
    int y = -1;
    int fps = 120;
    double opacity = 1.0;
    bool vsync = true;
    QString live2dQuality = QStringLiteral("balanced");
    int live2dScale = 100;
    double lipSyncMaxOpen = 0.55;
    int hitAlphaThreshold = 8;
    QString clickMotionActions = QStringLiteral("{}");
    QString pokeMotion;
    QString pokeExpression;
    QString defaultMotion;
    QString defaultExpression;
    bool idleActionsEnabled = true;
    bool randomActionsEnabled = true;
    bool dragLocked = false;
    bool moveAllRolesTogether = false;
    bool headTrackingEnabled = true;
    bool mutualGazeEnabled = false;
};

class PetProcessSupervisor final : public QObject {
    Q_OBJECT

public:
    explicit PetProcessSupervisor(QObject* parent = nullptr);
    ~PetProcessSupervisor() override;

    void start(PetLaunchSpec spec);
    void startAll(QList<PetLaunchSpec> specs);
    void stop();
    bool broadcastSettings(const QString& settingsJson);
    bool isRunning() const;
    int runningCount() const;
    int targetCount() const;

signals:
    void statusChanged(const QString& status);
    void rendererLog(const QString& message);
    void controlRequest(const QString& line);

private:
    struct ChildState;

    void launchPendingFleet();
    void launchNow(ChildState* child);
    void handleFinished(ChildState* child, int exitCode, int exitStatus);
    void scheduleRestart(ChildState* child);
    bool initializeIpcSession();
    void resetIpcSession();
    void requestFleetStop();
    void finalizeStoppedFleet();
    void publishPeerOffline(const QString& character);
    void pollIpcMessages();
    QString rendererProgram() const;

    QTimer ipcPollTimer_;
    QList<PetLaunchSpec> pendingSpecs_;
    std::vector<std::unique_ptr<ChildState>> children_;
    QString projectRoot_;
    bool stopping_ = true;
    bool relaunchAfterStop_ = false;
    bool finalizeScheduled_ = false;
    QString ipcSessionName_;
    QString supervisorPeerId_;
    std::unique_ptr<SharedMemoryLineQueue> inboundQueue_;
    std::unique_ptr<SharedMemoryLineQueue> reliableInboundQueue_;
    std::unique_ptr<SharedMemoryLineQueue> broadcastQueue_;
    std::unique_ptr<SharedMemoryLineQueue> controlQueue_;
};

} // namespace bandori
