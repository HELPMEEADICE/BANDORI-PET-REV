#include "pet_ipc_client.h"

#include "shared_memory_line_queue.h"

#include <QCoreApplication>
#include <QUuid>

#include <utility>

namespace bandori {

PetIpcClient::PetIpcClient(QString sessionName, QString character, QObject* parent)
    : QObject(parent),
      sessionName_(std::move(sessionName)),
      character_(std::move(character)) {
    const QString random = QUuid::createUuid()
                               .toString(QUuid::WithoutBraces)
                               .remove(QLatin1Char('-'))
                               .left(12);
    peerId_ = QStringLiteral("pet-%1-%2")
                  .arg(QCoreApplication::applicationPid())
                  .arg(random);
    pollTimer_.setInterval(30);
    heartbeatTimer_.setInterval(3'000);
    reconnectTimer_.setInterval(500);
    reconnectTimer_.setSingleShot(true);
    connect(&pollTimer_, &QTimer::timeout, this, &PetIpcClient::pollControl);
    connect(&heartbeatTimer_, &QTimer::timeout, this, &PetIpcClient::sendRegistration);
    connect(&reconnectTimer_, &QTimer::timeout, this, &PetIpcClient::start);
}

PetIpcClient::~PetIpcClient() {
    stop();
}

void PetIpcClient::start() {
    if (sessionName_.isEmpty()) {
        return;
    }
    if (!connectQueues()) {
        closeQueues();
        reconnectTimer_.start();
        return;
    }
    pollTimer_.start();
    heartbeatTimer_.start();
    sendRegistration();
}

void PetIpcClient::stop() {
    reconnectTimer_.stop();
    pollTimer_.stop();
    heartbeatTimer_.stop();
    sendUnregistration();
    closeQueues();
}

bool PetIpcClient::connectQueues() {
    if (reliableInboundQueue_ == nullptr || !reliableInboundQueue_->isAttached()) {
        reliableInboundQueue_ = SharedMemoryLineQueue::attach(
            makeSharedMemoryKey({sessionName_, QStringLiteral("main-reliable-in")}));
    }
    if (controlQueue_ == nullptr || !controlQueue_->isAttached()) {
        controlQueue_ = SharedMemoryLineQueue::attach(
            makeSharedMemoryKey({sessionName_, QStringLiteral("main-control")}));
    }
    if (broadcastQueue_ == nullptr || !broadcastQueue_->isAttached()) {
        broadcastQueue_ = SharedMemoryLineQueue::attach(
            makeSharedMemoryKey({sessionName_, QStringLiteral("main-out")}));
    }
    return reliableInboundQueue_ != nullptr && broadcastQueue_ != nullptr
        && controlQueue_ != nullptr;
}

void PetIpcClient::closeQueues() {
    reliableInboundQueue_.reset();
    broadcastQueue_.reset();
    controlQueue_.reset();
    registered_ = false;
}

void PetIpcClient::pollControl() {
    if (!connectQueues()) {
        pollTimer_.stop();
        heartbeatTimer_.stop();
        closeQueues();
        reconnectTimer_.start();
        return;
    }
    QStringList messages = broadcastQueue_->readAvailable();
    messages.append(controlQueue_->readAvailable());
    for (const QString& raw : messages) {
        const QString line = decodeIpcEnvelopeLine(raw);
        if (line == QStringLiteral("SHUTDOWN")) {
            emit shutdownRequested();
            return;
        }
        emit controlLineReceived(line);
    }
}

void PetIpcClient::sendRegistration() {
    if (reliableInboundQueue_ == nullptr) {
        return;
    }
    registered_ = reliableInboundQueue_->publish(encodeIpcEnvelope(
        peerId_,
        QStringLiteral("REGISTER\tPET\t%1").arg(character_),
        {},
        {},
        true));
}

void PetIpcClient::sendUnregistration() {
    if (!registered_ || reliableInboundQueue_ == nullptr) {
        return;
    }
    reliableInboundQueue_->publish(encodeIpcEnvelope(
        peerId_,
        QStringLiteral("UNREGISTER\tPET\t%1").arg(character_),
        {},
        {},
        true));
    registered_ = false;
}

} // namespace bandori
