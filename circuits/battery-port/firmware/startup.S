/* STM32G474 flash entry and Cortex-M4 exception vectors. */
.syntax unified
.cpu cortex-m4
.thumb
.section .isr_vector,"a",%progbits
.word __stack_top
.word Reset_Handler
.rept 13
.word Fault_Handler
.endr
.word SysTick_Handler
.rept 102
.word Fault_Handler
.endr

/* Arm EABI clear for a word-aligned destination and a byte count. */
.section .text.__aeabi_memclr4,"ax",%progbits
.global __aeabi_memclr4
.type __aeabi_memclr4, %function
.thumb_func
__aeabi_memclr4:
    movs r2, #0
.Lclear_words:
    cmp r1, #4
    blo .Lclear_bytes
    str r2, [r0], #4
    subs r1, #4
    b .Lclear_words
.Lclear_bytes:
    cbz r1, .Lclear_done
    strb r2, [r0], #1
    subs r1, #1
    bne .Lclear_bytes
.Lclear_done:
    bx lr
.size __aeabi_memclr4, . - __aeabi_memclr4
