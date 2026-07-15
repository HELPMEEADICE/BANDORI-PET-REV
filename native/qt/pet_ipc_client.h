#pragma once

#include <QObject>
#include <QString>
#include <QTimer>

#include <memory>

namespace bandori {

class SharedMemoryLineQueue;

class PetIpcClient final : public QObject {
    Q_OBJECT

public:
    PetIpcClient(QString sessionName, QString character, QObject* parent = nullptr);
    ~PetIpcClient() override;

    void start();
    void stop();
    bool publishLine(const QString& line, bool reliable = false);

signals:
    void shutdownRequested();
    void controlLineReceived(const QString& line);

private:
    bool connectQueues();
    void closeQueues();
    void pollControl();
    void sendRegistration();
    void sendUnregistration();

    QString sessionName_;
    QString character_;
    QString peerId_;
    bool registered_ = false;
    QTimer pollTimer_;
    QTimer heartbeatTimer_;
    QTimer reconnectTimer_;
    std::unique_ptr<SharedMemoryLineQueue> inboundQueue_;
    std::unique_ptr<SharedMemoryLineQueue> reliableInboundQueue_;
    std::unique_ptr<SharedMemoryLineQueue> broadcastQueue_;
    std::unique_ptr<SharedMemoryLineQueue> controlQueue_;
};

} // namespace bandori
