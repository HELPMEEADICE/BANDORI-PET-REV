#include "shared_memory_line_queue.h"

#include "bandori_ipc_ffi.h"

#include <QByteArray>
#include <QCryptographicHash>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSharedMemory>

#include <algorithm>
#include <limits>
#include <utility>

namespace bandori {

namespace {

class SharedMemoryLock final {
public:
    explicit SharedMemoryLock(QSharedMemory* memory)
        : memory_(memory), locked_(memory_ != nullptr && memory_->lock()) {}

    ~SharedMemoryLock() {
        if (locked_) {
            memory_->unlock();
        }
    }

    bool locked() const { return locked_; }

private:
    QSharedMemory* memory_;
    bool locked_;
};

bool reclaimStaleSegment(const QString& key) {
    QSharedMemory stale(key);
    if (!stale.attach()) {
        return false;
    }
    return stale.detach();
}

} // namespace

std::unique_ptr<SharedMemoryLineQueue> SharedMemoryLineQueue::create(
    const QString& key,
    int slotCount,
    int slotSize,
    bool allowDefaultFallback) {
    slotCount = std::max(slotCount, 1);
    slotSize = std::max(slotSize, 64);
    QList<int> candidates {slotCount};
    if (allowDefaultFallback && slotCount == 8) {
        candidates = {8, 4, 2};
    }

    QStringList errors;
    for (const int candidate : candidates) {
        const std::size_t size = bandori_ipc_queue_memory_size(
            static_cast<std::size_t>(candidate),
            static_cast<std::size_t>(slotSize));
        if (size == 0 || size > static_cast<std::size_t>(std::numeric_limits<int>::max())) {
            errors.append(QStringLiteral("invalid queue size"));
            continue;
        }
        auto memory = std::make_unique<QSharedMemory>(key);
        bool created = memory->create(static_cast<int>(size));
        if (!created && memory->error() == QSharedMemory::AlreadyExists && reclaimStaleSegment(key)) {
            memory = std::make_unique<QSharedMemory>(key);
            created = memory->create(static_cast<int>(size));
        }
        if (!created) {
            errors.append(memory->errorString());
            continue;
        }

        bool initialized = false;
        {
            SharedMemoryLock lock(memory.get());
            initialized = lock.locked() && memory->data() != nullptr
                && bandori_ipc_initialize_queue(
                    static_cast<std::uint8_t*>(memory->data()),
                    static_cast<std::size_t>(memory->size()),
                    static_cast<std::size_t>(candidate),
                    static_cast<std::size_t>(slotSize));
        }
        if (!initialized) {
            errors.append(QStringLiteral("failed to initialize queue memory"));
            memory->detach();
            continue;
        }
        return std::unique_ptr<SharedMemoryLineQueue>(new SharedMemoryLineQueue(
            key, std::move(memory), candidate, slotSize, 0));
    }
    Q_UNUSED(errors);
    return nullptr;
}

std::unique_ptr<SharedMemoryLineQueue> SharedMemoryLineQueue::attach(
    const QString& key,
    bool startAtTail) {
    auto memory = std::make_unique<QSharedMemory>(key);
    if (!memory->attach()) {
        return nullptr;
    }
    std::uint32_t slotCount = 0;
    std::uint32_t slotSize = 0;
    std::uint64_t nextSequence = 0;
    bool headerValid = false;
    {
        SharedMemoryLock lock(memory.get());
        headerValid = lock.locked() && memory->constData() != nullptr
            && bandori_ipc_read_header(
                static_cast<const std::uint8_t*>(memory->constData()),
                static_cast<std::size_t>(memory->size()),
                &slotCount,
                &slotSize,
                &nextSequence);
    }
    if (!headerValid) {
        memory->detach();
        return nullptr;
    }
    const std::uint64_t cursor = startAtTail
        ? nextSequence
        : nextSequence - std::min<std::uint64_t>(nextSequence, slotCount);
    return std::unique_ptr<SharedMemoryLineQueue>(new SharedMemoryLineQueue(
        key,
        std::move(memory),
        static_cast<int>(slotCount),
        static_cast<int>(slotSize),
        cursor));
}

SharedMemoryLineQueue::SharedMemoryLineQueue(
    QString key,
    std::unique_ptr<QSharedMemory> memory,
    int slotCount,
    int slotSize,
    std::uint64_t cursor)
    : key_(std::move(key)),
      memory_(std::move(memory)),
      slotCount_(slotCount),
      slotSize_(slotSize),
      cursor_(cursor) {}

SharedMemoryLineQueue::~SharedMemoryLineQueue() {
    close();
}

bool SharedMemoryLineQueue::publish(const QString& line) {
    const QByteArray payload = line.toUtf8();
    if (payload.isEmpty() || payload.size() > slotSize_ || !isAttached()) {
        lastError_ = QStringLiteral("invalid payload or detached queue");
        return false;
    }
    SharedMemoryLock lock(memory_.get());
    if (!lock.locked() || memory_->data() == nullptr) {
        lastError_ = QStringLiteral("queue lock failed");
        return false;
    }
    const bool published = bandori_ipc_publish(
        static_cast<std::uint8_t*>(memory_->data()),
        static_cast<std::size_t>(memory_->size()),
        reinterpret_cast<const std::uint8_t*>(payload.constData()),
        static_cast<std::size_t>(payload.size()),
        nullptr);
    lastError_ = published ? QString() : QStringLiteral("Rust queue publish failed");
    return published;
}

QStringList SharedMemoryLineQueue::readAvailable(int maximumMessages) {
    QStringList messages;
    if (!isAttached() || maximumMessages <= 0) {
        return messages;
    }
    SharedMemoryLock lock(memory_.get());
    if (!lock.locked() || memory_->constData() == nullptr) {
        lastError_ = QStringLiteral("queue lock failed");
        return messages;
    }
    QByteArray output(slotSize_, '\0');
    while (messages.size() < maximumMessages) {
        std::size_t outputLength = 0;
        std::uint64_t dropped = 0;
        const std::int32_t status = bandori_ipc_read_next(
            static_cast<const std::uint8_t*>(memory_->constData()),
            static_cast<std::size_t>(memory_->size()),
            &cursor_,
            reinterpret_cast<std::uint8_t*>(output.data()),
            static_cast<std::size_t>(output.size()),
            &outputLength,
            &dropped);
        droppedMessages_ += dropped;
        if (status == 0) {
            lastError_.clear();
            break;
        }
        if (status != 1 || outputLength > static_cast<std::size_t>(output.size())) {
            lastError_ = QStringLiteral("Rust queue read failed");
            break;
        }
        messages.append(QString::fromUtf8(output.constData(), static_cast<qsizetype>(outputLength)));
    }
    return messages;
}

bool SharedMemoryLineQueue::isAttached() const {
    return memory_ != nullptr && memory_->isAttached();
}

void SharedMemoryLineQueue::close() {
    if (memory_ != nullptr && memory_->isAttached()) {
        memory_->detach();
    }
    memory_.reset();
}

QString SharedMemoryLineQueue::key() const {
    return key_;
}

QString SharedMemoryLineQueue::lastError() const {
    return lastError_;
}

std::uint64_t SharedMemoryLineQueue::droppedMessages() const {
    return droppedMessages_;
}

QString makeSharedMemoryKey(const QStringList& parts) {
    const QByteArray raw = parts.join(QStringLiteral("::")).toUtf8();
    const QString digest = QString::fromLatin1(
        QCryptographicHash::hash(raw, QCryptographicHash::Sha1).toHex().left(16));
    const qsizetype labelStart = parts.size() > 2 ? parts.size() - 2 : 0;
    const QStringList labelParts = parts.mid(labelStart);
    const QString source = labelParts.join(QLatin1Char('-'));
    QString label;
    label.reserve(static_cast<qsizetype>(std::min<qsizetype>(source.size(), 48)));
    for (const QChar character : source) {
        if (label.size() >= 48) {
            break;
        }
        label.append(
            character.isLetterOrNumber() || character == QLatin1Char('.')
                || character == QLatin1Char('_') || character == QLatin1Char('-')
            ? character
            : QLatin1Char('-'));
    }
    if (label.isEmpty()) {
        label = QStringLiteral("ipc");
    }
    return QStringLiteral("BandoriPet-%1-%2").arg(label, digest);
}

QString encodeIpcEnvelope(
    const QString& senderId,
    const QString& line,
    const QString& excludePeerId,
    const QString& messageId,
    bool reliable) {
    QJsonObject envelope;
    QString normalizedLine = line;
    while (normalizedLine.endsWith(QLatin1Char('\r'))
           || normalizedLine.endsWith(QLatin1Char('\n'))) {
        normalizedLine.chop(1);
    }
    envelope.insert(QStringLiteral("sender"), senderId);
    envelope.insert(QStringLiteral("exclude"), excludePeerId);
    envelope.insert(QStringLiteral("line"), normalizedLine);
    envelope.insert(QStringLiteral("message_id"), messageId);
    envelope.insert(QStringLiteral("reliable"), reliable);
    return QString::fromUtf8(QJsonDocument(envelope).toJson(QJsonDocument::Compact));
}

QString decodeIpcEnvelopeLine(const QString& raw) {
    QJsonParseError error;
    const QJsonDocument document = QJsonDocument::fromJson(raw.toUtf8(), &error);
    if (error.error == QJsonParseError::NoError && document.isObject()) {
        const QJsonValue line = document.object().value(QStringLiteral("line"));
        if (line.isString()) {
            return line.toString();
        }
    }
    QString line = raw;
    while (line.endsWith(QLatin1Char('\r')) || line.endsWith(QLatin1Char('\n'))) {
        line.chop(1);
    }
    return line;
}

} // namespace bandori
