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
