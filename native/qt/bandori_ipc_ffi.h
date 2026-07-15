#pragma once

#include <cstddef>
#include <cstdint>

extern "C" {

std::size_t bandori_ipc_queue_memory_size(std::size_t slotCount, std::size_t slotSize);
bool bandori_ipc_initialize_queue(
    std::uint8_t* memory,
    std::size_t memoryLength,
    std::size_t slotCount,
    std::size_t slotSize);
bool bandori_ipc_read_header(
    const std::uint8_t* memory,
    std::size_t memoryLength,
    std::uint32_t* slotCount,
    std::uint32_t* slotSize,
    std::uint64_t* nextSequence);
bool bandori_ipc_publish(
    std::uint8_t* memory,
    std::size_t memoryLength,
    const std::uint8_t* payload,
    std::size_t payloadLength,
    std::uint64_t* sequence);
std::int32_t bandori_ipc_read_next(
    const std::uint8_t* memory,
    std::size_t memoryLength,
    std::uint64_t* cursor,
    std::uint8_t* output,
    std::size_t outputCapacity,
    std::size_t* outputLength,
    std::uint64_t* dropped);

}
