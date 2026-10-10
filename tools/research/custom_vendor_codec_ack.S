.syntax unified
.thumb
.cpu cortex-m4
.fpu fpv4-sp-d16

/* Preserve all general registers and APSR across the short C snapshot helper. */
.macro TRACE event
    stmdb sp!, {r0-r12,lr}
    mrs r0, APSR
    sub sp, sp, #8
    str r0, [sp]
    movs r0, #\event
    bl eoic_codec_record
    ldr r0, [sp]
    add sp, sp, #8
    msr APSR_nzcvqg, r0
    ldmia sp!, {r0-r12,lr}
.endm

/* Checkpoint helper; preserves the interrupted register/flag state. */
.macro PROGRESS event, value
    stmdb sp!, {r0-r12,lr}
    mrs r0, APSR
    sub sp, sp, #8
    str r0, [sp]
    movs r0, #\event
    movs r1, #\value
    bl eoic_codec_progress
    ldr r0, [sp]
    add sp, sp, #8
    msr APSR_nzcvqg, r0
    ldmia sp!, {r0-r12,lr}
.endm

/* Capture the outcome of an existing BNE while leaving its flags intact. */
.macro PROGRESS_BNE event
    stmdb sp!, {r0-r12,lr}
    mrs r2, APSR
    sub sp, sp, #8
    str r2, [sp]
    lsrs r1, r2, #30
    eors r1, r1, #1
    movs r0, #\event
    bl eoic_codec_progress
    ldr r0, [sp]
    add sp, sp, #8
    msr APSR_nzcvqg, r0
    ldmia sp!, {r0-r12,lr}
.endm

.section .text.codec_hooks,"ax",%progbits
.balign 4
.global eoic_hook_transaction_entry
.type eoic_hook_transaction_entry,%function
.thumb_func
eoic_hook_transaction_entry:
    strb r0, [r3]
    TRACE 0
    ldrb r3, [r3]
    cmp r3, #1
    PROGRESS_BNE 0
    bne 1f
    .balign 4
    ldr.w pc, [pc, #0]
    .word 0x0020a481
1:  .balign 4
    ldr.w pc, [pc, #0]
    .word 0x0020a435
.size eoic_hook_transaction_entry,.-eoic_hook_transaction_entry

/* 0x20a462 is the changed-configuration edge from the comparison at 0x20a452. */
.balign 4
.global eoic_hook_config_changed
.type eoic_hook_config_changed,%function
.thumb_func
eoic_hook_config_changed:
    PROGRESS 1, 1
    movw r2, #0x00e0
    movt r2, #0x4030
    strh r3, [r5, #2]
    strh r0, [r5]
    strh r1, [r6, #2]
    strh r7, [r6]
    .balign 4
    ldr.w pc, [pc, #0]
    .word 0x0020a46d
.size eoic_hook_config_changed,.-eoic_hook_config_changed

/* The opposite edge records an unchanged configuration comparison. */
.balign 4
.global eoic_hook_config_equal
.type eoic_hook_config_equal,%function
.thumb_func
eoic_hook_config_equal:
    PROGRESS 2, 1
    movw r6, #0x61f0
    movt r6, #0x2001
    ldrh.w r1, [r4, #0xc6]
    ldrh r2, [r6, #2]
    ldrh r0, [r4]
    .balign 4
    ldr.w pc, [pc, #0]
    .word 0x0020a585
.size eoic_hook_config_equal,.-eoic_hook_config_equal

.balign 4
.global eoic_hook_coefficient_progress
.type eoic_hook_coefficient_progress,%function
.thumb_func
eoic_hook_coefficient_progress:
    PROGRESS 3, 0
    ldr.w r3, [ip, #4]
    str.w r3, [lr, #0x10]
    .balign 4
    ldr.w pc, [pc, #0]
    .word 0x0020a6dd
.size eoic_hook_coefficient_progress,.-eoic_hook_coefficient_progress

.balign 4
.global eoic_hook_request_assert
.type eoic_hook_request_assert,%function
.thumb_func
eoic_hook_request_assert:
    PROGRESS 4, 0
    ldr r2, [r3]
    orr r2, r2, #0x400000
    str r2, [r3]
    TRACE 1
1:  ldr r2, [r3]
    lsls r1, r2, #7
    bpl 1b
    TRACE 2
    .balign 4
    ldr.w pc, [pc, #0]
    .word 0x0020a771
.size eoic_hook_request_assert,.-eoic_hook_request_assert

.balign 4
.global eoic_hook_success_cleanup
.type eoic_hook_success_cleanup,%function
.thumb_func
eoic_hook_success_cleanup:
    movs r2, #0
    strb r2, [r3]
    TRACE 6
    ldrb r2, [r7]
    rsb.w r2, r2, #1
    sxtb r2, r2
    strb r2, [r7]
    TRACE 5
    .balign 4
    ldr.w pc, [pc, #0]
    .word 0x0020a781
.size eoic_hook_success_cleanup,.-eoic_hook_success_cleanup

.balign 4
.global eoic_hook_request_clear
.type eoic_hook_request_clear,%function
.thumb_func
eoic_hook_request_clear:
    PROGRESS 5, 0
    str r2, [r3]
    TRACE 3
1:  ldr r2, [r3]
    lsls r2, r2, #7
    bmi 1b
    TRACE 4
    .balign 4
    ldr.w pc, [pc, #0]
    .word 0x0020a771
.size eoic_hook_request_clear,.-eoic_hook_request_clear

.balign 4
.global eoic_hook_error_first
.type eoic_hook_error_first,%function
.thumb_func
eoic_hook_error_first:
    ldr r1, [r2]
    bfi r1, r3, #28, #1
    str r1, [r2]
    TRACE 7
    movs r0, #3
    .balign 4
    ldr.w pc, [pc, #0]
    .word 0x0020a437
.size eoic_hook_error_first,.-eoic_hook_error_first

.balign 4
.global eoic_hook_error_second
.type eoic_hook_error_second,%function
.thumb_func
eoic_hook_error_second:
    ldr r1, [r2]
    bfi r1, r3, #29, #1
    str r1, [r2]
    TRACE 7
    movs r0, #3
    .balign 4
    ldr.w pc, [pc, #0]
    .word 0x0020a437
.size eoic_hook_error_second,.-eoic_hook_error_second
