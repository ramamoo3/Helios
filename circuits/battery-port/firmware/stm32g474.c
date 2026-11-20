#include "stm32g474xx.h"
#include "../bench-hrtim.h"

enum {
    CORE_HZ = 160000000, CYCLES_PER_US = CORE_HZ / 1000000,
    REQUEST_PIN = 6, PERMIT_PIN = 12, RUN_PIN = 10, ARM_PIN = 5, LED_PIN = 5,
    PRECHARGE_PIN = 1, ACK_PRIMARY_PIN = 2, ACK_SECONDARY_PIN = 12,
    ACK_MASK = (1u << ACK_PRIMARY_PIN) | (1u << ACK_SECONDARY_PIN),
    HRTIM_AF = 13,
    PRESS_MS = 20, RELEASE_MS = 20, PERMIT_TIMEOUT_MS = 2,
    ACK_TIMEOUT_US = 20, PRECHARGE_US = 7, PRECHARGE_GAP_US = 1,
    MID_FRAME = BENCH_HRTIM_PERIOD / 2,
    LATEST_UPDATE = BENCH_HRTIM_PERIOD * 3 / 4
};

#ifndef HELIOS_SHIFT
#define HELIOS_SHIFT 120
#endif

#if HELIOS_SHIFT != 120 && HELIOS_SHIFT != -120
#error "The bench image is built for +120 or -120 scheduler ticks"
#endif

static volatile uint32_t millis;
static bench_hrtim adapter;
static uint32_t last_midpoint;

#define MASTER (HRTIM1->sMasterRegs)
#define COMMON (HRTIM1->sCommonRegs)
#define OUTPUTS (HRTIM_OENR_TA1OEN | HRTIM_OENR_TA2OEN | HRTIM_OENR_TB1OEN | HRTIM_OENR_TB2OEN)
#define DISABLE_OUTPUTS (HRTIM_ODISR_TA1ODIS | HRTIM_ODISR_TA2ODIS | HRTIM_ODISR_TB1ODIS | HRTIM_ODISR_TB2ODIS)
#define COUNTERS (HRTIM_MCR_MCEN | HRTIM_MCR_TACEN | HRTIM_MCR_TBCEN)
#define MASK_UPDATES (HRTIM_CR1_TAUDIS | HRTIM_CR1_TBUDIS)

static bool request_high(void) { return (GPIOA->IDR & (1u << REQUEST_PIN)) != 0; }
static bool permit_high(void) { return (GPIOA->IDR & (1u << PERMIT_PIN)) != 0; }
static unsigned precharge_ack(void) { return GPIOB->IDR & ACK_MASK; }

static void gpio_mode(GPIO_TypeDef *port, unsigned pin, unsigned mode, unsigned pull)
{
    unsigned shift = 2u * pin;
    port->PUPDR = (port->PUPDR & ~(3u << shift)) | (pull << shift);
    port->MODER = (port->MODER & ~(3u << shift)) | (mode << shift);
}

static void disable_requests(void)
{
    GPIOB->BSRR = (1u << (RUN_PIN + 16)) | (1u << (ARM_PIN + 16)) |
                  (1u << (PRECHARGE_PIN + 16));
}

static void stop_timer(void)
{
    COMMON.ODISR = DISABLE_OUTPUTS;
    MASTER.MCR &= ~COUNTERS;
    COMMON.CR1 &= ~MASK_UPDATES;
    disable_requests();
    bench_hrtim_abort(&adapter);
}

void Fault_Handler(void)
{
    __disable_irq();
    if (RCC->APB2ENR & RCC_APB2ENR_HRTIM1EN)
        COMMON.ODISR = DISABLE_OUTPUTS;
    if (RCC->AHB2ENR & RCC_AHB2ENR_GPIOBEN)
        disable_requests();
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    (void)RCC->AHB2ENR;
    GPIOA->BSRR = 1u << LED_PIN;
    gpio_mode(GPIOA, LED_PIN, 1, 0);
    __DSB();
    for (;;) __NOP();
}

void SysTick_Handler(void) { ++millis; }

static void wait_register(volatile uint32_t *reg, uint32_t mask, uint32_t value)
{
    for (unsigned retries = 2000000; retries > 0; --retries)
        if ((*reg & mask) == value)
            return;
    Fault_Handler();
}

static void configure_clock(void)
{
    RCC->APB1ENR1 |= RCC_APB1ENR1_PWREN;
    (void)RCC->APB1ENR1;
    PWR->CR1 = (PWR->CR1 & ~PWR_CR1_VOS) | PWR_CR1_VOS_0;
    wait_register(&PWR->SR2, PWR_SR2_VOSF, 0);
    PWR->CR5 &= ~PWR_CR5_R1MODE;

    RCC->CR |= RCC_CR_HSION;
    wait_register(&RCC->CR, RCC_CR_HSIRDY, RCC_CR_HSIRDY);
    FLASH->ACR = (FLASH->ACR & ~FLASH_ACR_LATENCY) | FLASH_ACR_LATENCY_4WS;
    wait_register(&FLASH->ACR, FLASH_ACR_LATENCY, FLASH_ACR_LATENCY_4WS);
    /* HSI16 / 4 × 80 / 2 = 160 MHz. Stage AHB at /2 during the switch. */
    RCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_HSI | (3u << RCC_PLLCFGR_PLLM_Pos) |
                   (80u << RCC_PLLCFGR_PLLN_Pos) | RCC_PLLCFGR_PLLREN;
    RCC->CR |= RCC_CR_PLLON;
    wait_register(&RCC->CR, RCC_CR_PLLRDY, RCC_CR_PLLRDY);
    RCC->CFGR = (RCC->CFGR & ~(RCC_CFGR_HPRE | RCC_CFGR_SW)) |
                RCC_CFGR_HPRE_DIV2 | RCC_CFGR_SW_PLL;
    wait_register(&RCC->CFGR, RCC_CFGR_SWS, RCC_CFGR_SWS_PLL);
    for (unsigned i = 0; i < 128; ++i) __NOP();
    RCC->CFGR &= ~RCC_CFGR_HPRE;
    FLASH->ACR |= FLASH_ACR_PRFTEN | FLASH_ACR_ICEN;
    if (SysTick_Config(CORE_HZ / 1000u) != 0)
        Fault_Handler();
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
}

static void configure_timer(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_HRTIM1EN;
    (void)RCC->APB2ENR;
    COMMON.ODISR = DISABLE_OUTPUTS;
    COMMON.DLLCR = HRTIM_DLLCR_CAL;
    wait_register(&COMMON.ISR, HRTIM_ISR_DLLRDY, HRTIM_ISR_DLLRDY);
    COMMON.DLLCR = HRTIM_DLLCR_CALEN; /* Periodic calibration, CALRTE = 0. */
    MASTER.MCR = HRTIM_MCR_CONT | HRTIM_MCR_CK_PSC_1 | HRTIM_MCR_MREPU;
    MASTER.MPER = BENCH_HRTIM_PERIOD;
    MASTER.MREP = 0;
    MASTER.MCMP1R = MID_FRAME;
    /* GPIO source, active low, raw input. ENABLE is the sole nonzero bit. */
    COMMON.FLTINR1 = HRTIM_FLTINR1_FLT1E;
    for (unsigned i = 0; i < 2; ++i) {
        HRTIM_Timerx_TypeDef *timer = &HRTIM1->sTimerxRegs[i];
        /* The prescaler must be programmed before period or compare values. */
        timer->TIMxCR = HRTIM_TIMCR_CONT | HRTIM_TIMCR_CK_PSC_1;
        timer->PERxR = BENCH_HRTIM_PERIOD;
        timer->SETx1R = HRTIM_SET1R_CMP1;
        timer->RSTx1R = HRTIM_RST1R_CMP2;
        timer->SETx2R = HRTIM_SET2R_CMP3;
        timer->RSTx2R = HRTIM_RST2R_CMP4;
        timer->OUTxR = HRTIM_OUTR_FAULT1_1 | HRTIM_OUTR_FAULT2_1;
        timer->FLTxR = HRTIM_FLTR_FLT1EN;
        timer->TIMxCR |= HRTIM_TIMCR_PREEN | HRTIM_TIMCR_MSTU;
    }
    /* Select the HRTIM AF only after idle/fault states have been programmed. */
    for (unsigned pin = 8; pin <= PERMIT_PIN; ++pin) {
        unsigned shift = 4u * (pin - 8u);
        GPIOA->AFR[1] = (GPIOA->AFR[1] & ~(15u << shift)) | (HRTIM_AF << shift);
        if (pin != PERMIT_PIN)
            GPIOA->OSPEEDR |= 2u << (2u * pin);
        gpio_mode(GPIOA, pin, 2, 2);
    }
}

static void program_compares(HRTIM_Timerx_TypeDef *timer, bench_hrtim_compares values)
{
    timer->CMP1xR = values.cmp1;
    timer->CMP2xR = values.cmp2;
    timer->CMP3xR = values.cmp3;
    timer->CMP4xR = values.cmp4;
}

static bool start_permitted(void)
{
    return request_high() && permit_high() && !(COMMON.ISR & HRTIM_ISR_FLT1);
}

static bool wait_for_ack(unsigned expected)
{
    uint32_t start = DWT->CYCCNT;
    while (DWT->CYCCNT - start < ACK_TIMEOUT_US * CYCLES_PER_US) {
        if (!start_permitted())
            return false;
        if (precharge_ack() == expected)
            return true;
    }
    return false;
}

static bool hold_precharge_state(unsigned expected, unsigned microseconds)
{
    uint32_t start = DWT->CYCCNT;
    do {
        if (!start_permitted() || precharge_ack() != expected)
            return false;
    } while (DWT->CYCCNT - start < microseconds * CYCLES_PER_US);
    return true;
}

static bool prepare_bootstrap(void)
{
    /* The timer outputs are disabled when entering this handshake. */
    if (precharge_ack())
        return false;
    COMMON.ICR = HRTIM_ICR_FLT1C;
    if (!start_permitted())
        return false;
    GPIOB->BSRR = 1u << PRECHARGE_PIN;
    bool charged = wait_for_ack(ACK_MASK) && hold_precharge_state(ACK_MASK, PRECHARGE_US);
    GPIOB->BSRR = 1u << (PRECHARGE_PIN + 16);
    return charged && wait_for_ack(0) && hold_precharge_state(0, PRECHARGE_GAP_US);
}

static bool start_timer(void)
{
    bench_hrtim_frame frame;
    if (!request_high() || !bench_hrtim_next(&adapter, true, permit_high(), HELIOS_SHIFT, &frame))
        return false;
    for (unsigned i = 0; i < 2; ++i) {
        HRTIM_Timerx_TypeDef *timer = &HRTIM1->sTimerxRegs[i];
        timer->CNTxR = 0;
        timer->RSTx1R = HRTIM_RST1R_CMP2 | HRTIM_RST1R_SRT;
        timer->RSTx2R = HRTIM_RST2R_CMP4 | HRTIM_RST2R_SRT;
    }
    MASTER.MCNTR = 0;
    program_compares(&HRTIM1->sTimerxRegs[0], frame.primary);
    program_compares(&HRTIM1->sTimerxRegs[1], frame.secondary);
    COMMON.CR2 = HRTIM_CR2_TASWU | HRTIM_CR2_TBSWU;
    MASTER.MICR = HRTIM_MICR_MCMP1;
    if (!start_permitted() || precharge_ack())
        return false;
    COMMON.OENR = OUTPUTS;
    MASTER.MCR |= COUNTERS;
    last_midpoint = DWT->CYCCNT - 10u * CYCLES_PER_US;
    return true;
}

static bool service_timer(void)
{
    if (!start_permitted() || precharge_ack() ||
        DWT->CYCCNT - last_midpoint >= 24u * CYCLES_PER_US)
        return false;
    if (!(MASTER.MISR & HRTIM_MISR_MCMP1))
        return true;

    uint32_t counter = MASTER.MCNTR;
    if (counter < MID_FRAME || counter >= LATEST_UPDATE)
        return false;
    MASTER.MICR = HRTIM_MICR_MCMP1;
    last_midpoint = DWT->CYCCNT;
    bench_hrtim_frame frame;
    if (!bench_hrtim_next(&adapter, true, true, HELIOS_SHIFT, &frame))
        return false;
    COMMON.CR1 |= MASK_UPDATES;
    program_compares(&HRTIM1->sTimerxRegs[0], frame.primary);
    program_compares(&HRTIM1->sTimerxRegs[1], frame.secondary);
    counter = MASTER.MCNTR;
    if (counter < MID_FRAME || counter >= LATEST_UPDATE)
        return false;
    COMMON.CR1 &= ~MASK_UPDATES;
    return true;
}

static void configure_watchdog(void)
{
    IWDG->KR = 0xCCCC; /* Start with its independent oscillator. */
    IWDG->KR = 0x5555;
    IWDG->PR = 2;      /* Divider 16. About 64 ms at nominal 32 kHz. */
    IWDG->RLR = 127;
    wait_register(&IWDG->SR, IWDG_SR_PVU | IWDG_SR_RVU, 0);
    IWDG->KR = 0xAAAA;
}

static void run_bench(void)
{
    enum { WAIT_RELEASE, WAIT_PRESS, WAIT_PERMIT, RUNNING } mode = WAIT_RELEASE;
    uint32_t changed = millis;
    uint32_t watchdog_tick = changed;
    for (;;) {
        uint32_t now = millis;
        bool request = request_high();
        switch (mode) {
        case WAIT_RELEASE:
            if (request || permit_high() || precharge_ack())
                changed = now;
            else if (now - changed >= RELEASE_MS) {
                bench_hrtim_frame unused;
                bench_hrtim_next(&adapter, false, false, HELIOS_SHIFT, &unused);
                mode = WAIT_PRESS;
                changed = now;
            }
            break;
        case WAIT_PRESS:
            if (permit_high() || precharge_ack()) {
                mode = WAIT_RELEASE;
                changed = now;
            } else if (!request) {
                changed = now;
            } else if (now - changed >= PRESS_MS) {
                GPIOB->BSRR = 1u << ARM_PIN;
                uint32_t start = DWT->CYCCNT;
                while (DWT->CYCCNT - start < 2u * CYCLES_PER_US) __NOP();
                GPIOB->BSRR = 1u << (ARM_PIN + 16);
                GPIOB->BSRR = 1u << RUN_PIN;
                mode = WAIT_PERMIT;
                changed = now;
            }
            break;
        case WAIT_PERMIT:
            if (request) {
                if (permit_high()) {
                    if (prepare_bootstrap() && start_timer()) {
                        mode = RUNNING;
                        break;
                    }
                } else if (now - changed < PERMIT_TIMEOUT_MS) {
                    break;
                }
            }
            stop_timer();
            mode = WAIT_RELEASE;
            changed = now;
            break;
        case RUNNING:
            if (!service_timer()) {
                stop_timer();
                mode = WAIT_RELEASE;
                changed = now;
            }
            break;
        }
        if (now != watchdog_tick) {
            IWDG->KR = 0xAAAA;
            watchdog_tick = now;
        }
    }
}

extern uint32_t __data_load, __data_start, __data_end, __bss_start, __bss_end;

void Reset_Handler(void)
{
    /* Explicit stores keep reset independent of compiler runtime routines. */
    const uint32_t *src = &__data_load;
    for (volatile uint32_t *dest = &__data_start; dest < &__data_end;)
        *dest++ = *src++;
    for (volatile uint32_t *dest = &__bss_start; dest < &__bss_end;)
        *dest++ = 0;
    SCB->VTOR = 0x08000000u;
    __DSB();
    __ISB();
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN | RCC_AHB2ENR_GPIOBEN;
    (void)RCC->AHB2ENR;
    disable_requests();
    gpio_mode(GPIOB, RUN_PIN, 1, 2);
    gpio_mode(GPIOB, ARM_PIN, 1, 2);
    gpio_mode(GPIOB, PRECHARGE_PIN, 1, 2);
    gpio_mode(GPIOB, ACK_PRIMARY_PIN, 0, 2);
    gpio_mode(GPIOB, ACK_SECONDARY_PIN, 0, 2);
    GPIOA->BSRR = 1u << (LED_PIN + 16);
    gpio_mode(GPIOA, LED_PIN, 1, 0);
    gpio_mode(GPIOA, REQUEST_PIN, 0, 2);
    configure_clock();
    configure_timer();
    configure_watchdog();
    run_bench();
}
