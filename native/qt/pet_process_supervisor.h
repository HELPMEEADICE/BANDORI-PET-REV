#pragma once

#include <QObject>
#include <QElapsedTimer>
#include <QProcess>
#include <QString>
#include <QTimer>

#include <memory>

namespace bandori {

class SharedMemoryLineQueue;

struct PetLaunchSpec {
    QString projectRoot;
    QString userModelsRoot;
    QString modelPath;
    QString character;
    QString format = QStringLiteral("moc3");
    int width = 400;
    int height = 650;
    int fps = 120;
    double opacity = 1.0;
    double lipSyncMaxOpen = 0.55;
    int hitAlphaThreshold = 8;
    bool dragLocked = false;
    bool moveAllRolesTogether = false;
};

class PetProcessSupervisor final : public QObject {
    Q_OBJECT

public:
    explicit PetProcessSupervisor(QObject* parent = nullptr);
    ~PetProcessSupervisor() override;

    void start(PetLaunchSpec spec);
    void stop();
    bool isRunning() const;

signals:
    void statusChanged(const QString& status);
    void rendererLog(const QString& message);

private:
    void launchNow();
    void handleFinished(int exitCode, QProcess::ExitStatus exitStatus);
    void scheduleRestart();
    bool initializeIpcSession();
    void requestProcessStop();
    void pollIpcMessages();
    QString rendererProgram() const;

    QProcess process_;
    QTimer restartTimer_;
    QTimer terminateTimer_;
    QTimer killTimer_;
    QTimer ipcPollTimer_;
    PetLaunchSpec spec_;
    bool stopping_ = true;
    bool relaunchAfterStop_ = false;
    bool replaceIpcSessionAfterStop_ = false;
    int consecutiveFailures_ = 0;
    QElapsedTimer processUptime_;
    QString ipcSessionName_;
    QString supervisorPeerId_;
    std::unique_ptr<SharedMemoryLineQueue> inboundQueue_;
    std::unique_ptr<SharedMemoryLineQueue> reliableInboundQueue_;
    std::unique_ptr<SharedMemoryLineQueue> broadcastQueue_;
    std::unique_ptr<SharedMemoryLineQueue> controlQueue_;
};

} // namespace bandori
