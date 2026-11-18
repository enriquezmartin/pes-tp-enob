#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/dma.h"
#include "hardware/timer.h"
#include "hardware/clocks.h"
#include "hardware/adc.h"

#define ADC_PIN 26
#define ADC_CHANNEL 0
#define NUM_SAMPLES 2048

// Configuración de la frecuencia de muestreo (Fs)
// El reloj base del ADC opera a 48 MHz.
// Fs = 48,000,000 / (clkdiv + 1)
// Para Fs = 50 kHz: clkdiv = (48,000,000 / 50,000) - 1 = 959
#define ADC_CLKDIV 959.0f

int64_t alarm_callback(alarm_id_t id, void *user_data) {
    // Put your timeout handler code in here
    return 0;
}

// Buffer donde el DMA depositará las lecturas del ADC (cada muestra es de 12 bits -> uint16_t)
uint16_t adc_buffer[NUM_SAMPLES];

int dma_chan;

void init_adc_dma(void) {
    // 1. Inicializar el periférico ADC
    adc_init();
    adc_gpio_init(ADC_PIN);          // Configura el GPIO 26 como entrada analógica
    adc_select_input(ADC_CHANNEL);   // Selecciona el canal 0

    // 2. Configurar el divisor de reloj del ADC para fijar la Frecuencia de Muestreo (Fs)
    adc_set_clkdiv(ADC_CLKDIV);

    // 3. Configurar la FIFO del ADC para trabajar con DMA
    adc_fifo_setup(
        true,    // Habilitar la FIFO del ADC
        true,    // Habilitar la solicitud de transferencia por DMA (DREQ)
        1,       // Umbral de la FIFO (disparar DMA con al menos 1 muestra disponible)
        false,   // No incluir bit de error en los datos
        false    // Mantener la muestra a 12 bits (no reducir a 8 bits)
    );

    // 4. Solicitar un canal DMA libre
    dma_chan = dma_claim_unused_channel(true);

    // 5. Configurar los parámetros del canal DMA
    dma_channel_config cfg = dma_channel_get_default_config(dma_chan);
    channel_config_set_transfer_data_size(&cfg, DMA_SIZE_16); // Cada transferencia es de 16 bits (uint16_t)
    channel_config_set_read_increment(&cfg, false);           // La fuente es fija (registro FIFO del ADC)
    channel_config_set_write_increment(&cfg, true);            // El destino avanza en memoria (adc_buffer)
    channel_config_set_dreq(&cfg, DREQ_ADC);                   // El avance del DMA es sincronizado por el ADC

    // Aplicar la configuración al canal DMA
    dma_channel_configure(
        dma_chan,       // Canal a configurar
        &cfg,           // config creada arriba
        adc_buffer,     // Dirección de destino (memoria RAM)
        &adc_hw->fifo,  // Dirección de origen (registro FIFO del ADC)
        NUM_SAMPLES,    // Número total de transferencias
        false           // No iniciar inmediatamente
    );
}

void capture_adc_block(void) {
    // Vaciar cualquier dato residual en la FIFO del ADC
    adc_fifo_drain();
    // Reiniciar la dirección de destino del DMA y recargar el contador de muestras
    dma_channel_set_write_addr(dma_chan, adc_buffer, true);
    // Iniciar la conversión continua del ADC
    adc_run(true);
    // Esperar a que el DMA termine de transferir las NUM_SAMPLES muestras
    dma_channel_wait_for_finish_blocking(dma_chan);
    // Detener la conversión del ADC hasta la próxima captura
    adc_run(false);
}

int main()
{
    stdio_init_all();
    //Esperar a que el puerto USB se abra en la PC
    while(!stdio_usb_connected()) { 
        sleep_ms(100);
    }

    // Timer example code - This example fires off the callback after 2000ms
    add_alarm_in_ms(2000, alarm_callback, NULL, false);
    // For more examples of timer use see https://github.com/raspberrypi/pico-examples/tree/master/timer

    printf("System Clock Frequency is %d Hz\n", clock_get_hz(clk_sys));
    printf("USB Clock Frequency is %d Hz\n", clock_get_hz(clk_usb));
    // For more examples of clocks use see https://github.com/raspberrypi/pico-examples/tree/master/clocks
    
    init_adc_dma();

    printf("=== Firmware de Captura de ADC para Muestreo de ENOB Iniciado ===\n");

    while (true) {
        // Enviar un marcador de inicio para que Python sincronice la ráfaga
        printf("START_BURST\n");

        // Capturar bloque de muestras vía DMA
        capture_adc_block();

        // Enviar las muestras capturadas en texto plano por el puerto serie
        for (int i = 0; i < NUM_SAMPLES; i++) {
            printf("%u\n", adc_buffer[i]);
        }

        printf("END_BURST\n");

        // Pausa entre capturas para permitir procesamiento en la PC
        sleep_ms(1000);
    }
    return 0;
}
