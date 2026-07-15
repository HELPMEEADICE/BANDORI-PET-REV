use crate::ipc::{initialize_queue, publish, queue_memory_size, read_available, read_queue_header};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::slice;
use std::str;

pub const READ_ERROR: i32 = -1;
pub const READ_BUFFER_TOO_SMALL: i32 = -2;
pub const READ_EMPTY: i32 = 0;
pub const READ_MESSAGE: i32 = 1;

#[unsafe(no_mangle)]
pub extern "C" fn bandori_ipc_queue_memory_size(slot_count: usize, slot_size: usize) -> usize {
    queue_memory_size(slot_count, slot_size).unwrap_or(0)
}

#[unsafe(no_mangle)]
/// Reads queue metadata from a locked shared-memory region.
///
/// # Safety
/// `memory` must be readable for `memory_len` bytes. All three output pointers
/// must be non-null and writable. The queue must remain locked for the call.
pub unsafe extern "C" fn bandori_ipc_read_header(
    memory: *const u8,
    memory_len: usize,
    slot_count_out: *mut u32,
    slot_size_out: *mut u32,
    next_sequence_out: *mut u64,
) -> bool {
    ffi_bool(|| {
        if slot_count_out.is_null() || slot_size_out.is_null() || next_sequence_out.is_null() {
            return Err(());
        }
        // SAFETY: guaranteed by the C ABI caller and checked for null below.
        let memory = unsafe { bytes(memory, memory_len)? };
        let header = read_queue_header(memory).map_err(|_| ())?;
        // SAFETY: output pointers were checked above.
        unsafe {
            slot_count_out.write(header.slot_count);
            slot_size_out.write(header.slot_size);
            next_sequence_out.write(header.next_sequence);
        }
        Ok(())
    })
}

#[unsafe(no_mangle)]
/// Initializes a locked shared-memory region with the Bandori queue header.
///
/// # Safety
/// `memory` must be writable for `memory_len` bytes and exclusively locked by
/// the caller for the duration of this call.
pub unsafe extern "C" fn bandori_ipc_initialize_queue(
    memory: *mut u8,
    memory_len: usize,
    slot_count: usize,
    slot_size: usize,
) -> bool {
    ffi_bool(|| {
        // SAFETY: guaranteed by the C ABI caller and checked for null below.
        let memory = unsafe { memory_slice_mut(memory, memory_len)? };
        initialize_queue(memory, slot_count, slot_size).map_err(|_| ())
    })
}

#[unsafe(no_mangle)]
/// Publishes one UTF-8 line into a locked shared-memory queue.
///
/// # Safety
/// The memory and payload pointers must be valid for their lengths. Queue
/// memory must be exclusively locked. `sequence_out` may be null.
pub unsafe extern "C" fn bandori_ipc_publish(
    memory: *mut u8,
    memory_len: usize,
    payload: *const u8,
    payload_len: usize,
    sequence_out: *mut u64,
) -> bool {
    ffi_bool(|| {
        // SAFETY: guaranteed by the C ABI caller and checked for null below.
        let memory = unsafe { memory_slice_mut(memory, memory_len)? };
        // SAFETY: guaranteed by the C ABI caller and checked for null below.
        let payload = unsafe { bytes(payload, payload_len)? };
        let line = str::from_utf8(payload).map_err(|_| ())?;
        let sequence = publish(memory, line).map_err(|_| ())?;
        if !sequence_out.is_null() {
            // SAFETY: the caller supplied a writable output pointer.
            unsafe { sequence_out.write(sequence) };
        }
        Ok(())
    })
}

#[unsafe(no_mangle)]
/// Reads at most one queued UTF-8 message from locked shared memory.
///
/// Returns `1` for a message, `0` when empty, `-2` if the output buffer is too
/// small, or `-1` for invalid input/header. Dropped messages are accumulated in
/// `dropped_out` for this read operation.
///
/// # Safety
/// All pointers must be valid for their stated lengths. `cursor` and
/// `output_len` must be writable; `dropped_out` may be null. The queue must be
/// locked for the duration of this call.
pub unsafe extern "C" fn bandori_ipc_read_next(
    memory: *const u8,
    memory_len: usize,
    cursor: *mut u64,
    output: *mut u8,
    output_capacity: usize,
    output_len: *mut usize,
    dropped_out: *mut u64,
) -> i32 {
    let result = catch_unwind(AssertUnwindSafe(|| {
        if cursor.is_null() || output_len.is_null() {
            return Err(READ_ERROR);
        }
        // SAFETY: guaranteed by the C ABI caller and checked for null below.
        let memory = unsafe { bytes(memory, memory_len) }.map_err(|_| READ_ERROR)?;
        // SAFETY: non-null checked above; caller provides exclusive access.
        let cursor = unsafe { &mut *cursor };
        let batch = read_available(memory, cursor, Some(1)).map_err(|_| READ_ERROR)?;
        if !dropped_out.is_null() {
            // SAFETY: caller supplied a writable optional output pointer.
            unsafe { dropped_out.write(batch.dropped) };
        }
        let Some(message) = batch.messages.first() else {
            // SAFETY: non-null checked above.
            unsafe { output_len.write(0) };
            return Ok(READ_EMPTY);
        };
        let message = message.as_bytes();
        if output.is_null() || output_capacity < message.len() {
            *cursor = cursor.saturating_sub(1);
            // SAFETY: non-null checked above.
            unsafe { output_len.write(message.len()) };
            return Ok(READ_BUFFER_TOO_SMALL);
        }
        // SAFETY: output capacity was validated above and regions cannot
        // overlap because one belongs to shared memory and one to the caller.
        unsafe { std::ptr::copy_nonoverlapping(message.as_ptr(), output, message.len()) };
        // SAFETY: non-null checked above.
        unsafe { output_len.write(message.len()) };
        Ok(READ_MESSAGE)
    }));
    match result {
        Ok(Ok(status)) => status,
        Ok(Err(status)) => status,
        Err(_) => READ_ERROR,
    }
}

fn ffi_bool(operation: impl FnOnce() -> Result<(), ()>) -> bool {
    matches!(catch_unwind(AssertUnwindSafe(operation)), Ok(Ok(())))
}

unsafe fn memory_slice_mut<'a>(memory: *mut u8, len: usize) -> Result<&'a mut [u8], ()> {
    if memory.is_null() || len == 0 {
        return Err(());
    }
    // SAFETY: caller guarantees the allocation and exclusive lock.
    Ok(unsafe { slice::from_raw_parts_mut(memory, len) })
}

unsafe fn bytes<'a>(value: *const u8, len: usize) -> Result<&'a [u8], ()> {
    if value.is_null() || len == 0 {
        return Err(());
    }
    // SAFETY: caller guarantees the allocation for the duration of the call.
    Ok(unsafe { slice::from_raw_parts(value, len) })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ptr;

    #[test]
    fn c_abi_round_trips_queue_messages_and_cursor() {
        let size = bandori_ipc_queue_memory_size(2, 64);
        let mut memory = vec![0; size];
        // SAFETY: vectors and output pointers remain valid for every call.
        unsafe {
            assert!(bandori_ipc_initialize_queue(
                memory.as_mut_ptr(),
                memory.len(),
                2,
                64,
            ));
            assert!(bandori_ipc_publish(
                memory.as_mut_ptr(),
                memory.len(),
                b"hello".as_ptr(),
                5,
                ptr::null_mut(),
            ));
            let mut cursor = 0;
            let mut output = [0; 64];
            let mut output_len = 0;
            let mut dropped = 0;
            assert_eq!(
                bandori_ipc_read_next(
                    memory.as_ptr(),
                    memory.len(),
                    &mut cursor,
                    output.as_mut_ptr(),
                    output.len(),
                    &mut output_len,
                    &mut dropped,
                ),
                READ_MESSAGE
            );
            assert_eq!(&output[..output_len], b"hello");
            assert_eq!(cursor, 1);
            assert_eq!(dropped, 0);
            assert_eq!(
                bandori_ipc_read_next(
                    memory.as_ptr(),
                    memory.len(),
                    &mut cursor,
                    output.as_mut_ptr(),
                    output.len(),
                    &mut output_len,
                    &mut dropped,
                ),
                READ_EMPTY
            );
        }
    }

    #[test]
    fn c_abi_rejects_null_and_non_utf8_payloads() {
        // SAFETY: invalid pointers are intentional and rejected before access.
        unsafe {
            assert!(!bandori_ipc_initialize_queue(ptr::null_mut(), 0, 1, 64));
            let mut memory = vec![0; bandori_ipc_queue_memory_size(1, 64)];
            assert!(bandori_ipc_initialize_queue(
                memory.as_mut_ptr(),
                memory.len(),
                1,
                64,
            ));
            assert!(!bandori_ipc_publish(
                memory.as_mut_ptr(),
                memory.len(),
                [0xff].as_ptr(),
                1,
                ptr::null_mut(),
            ));
        }
    }
}
