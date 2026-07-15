#pragma once

#include <QString>
#include <QStringList>

#include <cstdint>
#include <memory>

class QSharedMemory;

namespace bandori {

class SharedMemoryLineQueue final {
public:
    static std::unique_ptr<SharedMemoryLineQueue> create(
        const QString& key,
        int slotCount = 8,
        int slotSize = 65'536,
        bool allowDefaultFallback = true);
    static std::unique_ptr<SharedMemoryLineQueue> attach(
        const QString& key,
        bool startAtTail = true);

    ~SharedMemoryLineQueue();

    SharedMemoryLineQueue(const SharedMemoryLineQueue&) = delete;
    SharedMemoryLineQueue& operator=(const SharedMemoryLineQueue&) = delete;

    bool publish(const QString& line);
    QStringList readAvailable(int maximumMessages = 200);
    bool isAttached() const;
    void close();

    QString key() const;
    QString lastError() const;
    std::uint64_t droppedMessages() const;

private:
    SharedMemoryLineQueue(
        QString key,
        std::unique_ptr<QSharedMemory> memory,
        int slotCount,
        int slotSize,
        std::uint64_t cursor);

    QString key_;
    std::unique_ptr<QSharedMemory> memory_;
    int slotCount_ = 0;
    int slotSize_ = 0;
    std::uint64_t cursor_ = 0;
    std::uint64_t droppedMessages_ = 0;
    QString lastError_;
};

QString makeSharedMemoryKey(const QStringList& parts);
QString encodeIpcEnvelope(
    const QString& senderId,
    const QString& line,
    const QString& excludePeerId = {},
    const QString& messageId = {},
    bool reliable = false);
QString decodeIpcEnvelopeLine(const QString& raw);

} // namespace bandori
