import time
import numpy as np
import scipy.signal as sig
import matplotlib.pyplot as plt
import serial
import serial.tools.list_ports

# ============================================================================
# CONFIGURACIÓN Y PARÁMETROS
# ============================================================================
PORT = "COM4"  # Cambiar por el puerto correcto (ej: '/dev/ttyACM0' en Linux / Mac)
BAUD_RATE = 115200

# = Estos datos se los deben anotar para el informe de ENOB =
NUM_SAMPLES = 2048  # Muestras N recibidas desde la Pico 2
FS = 50000.0  # Frecuencia de muestreo (50 kHz)
V_REF = 3.3  # Rango de referencia del ADC de la Pico 2 (0V a 3.3V)
ADC_BITS = 12  # Resolución nominal del ADC

# ============================================================================
# FUNCIÓN DE CONEXIÓN SERIE
# ============================================================================
def abrir_puerto_serie(puerto, baudios):
    try:
        ser = serial.Serial(puerto, baudios, timeout=2)
        time.sleep(1)  # Esperar estabilización del puerto
        print(f"[+] Conectado exitosamente a {puerto}")
        return ser
    except Exception as e:
        print(f"[-] Error al abrir el puerto serie {puerto}: {e}")
        print("\nPuertos disponibles identificados:")
        ports = serial.tools.list_ports.comports()
        for p in ports:
            print(f"  -> {p.device}: {p.description}")
        return None

# ============================================================================
# FUNCIÓN PARA CAPTURAR RÁFAGA DE DATOS
# ============================================================================
def capturar_rafaga(ser):
    raw_data = []
    print("[*] Esperando sincronización de ráfaga (START_BURST)...")

    # Esperar el encabezado de la Pico 2
    while True:
        linea = ser.readline().decode('utf-8', errors='ignore').strip()
        if linea == "START_BURST":
            break

    # Leer exactamente NUM_SAMPLES valores numéricos
    while len(raw_data) < NUM_SAMPLES:
        linea = ser.readline().decode('utf-8', errors='ignore').strip()
        if linea.isdigit():
            raw_data.append(int(linea))

    return np.array(raw_data, dtype=float)

# ============================================================================
# CÁLCULO DE ENOB Y PROCESAMIENTO DSP
# ============================================================================
def procesar_y_calcular_enob(adc_counts):
    # 1. Convertir cuentas de ADC a Voltaje analógico (0 - 3.3 V)
    v_signal = (adc_counts / ((2**ADC_BITS) - 1)) * V_REF

    # 2. Estadística descriptiva temporal (Media y Desviación Estándar)[cite: 3]
    v_mean = np.mean(v_signal)
    v_std = np.std(v_signal)

    # 3. Remover componente de Corriente Continua (DC Offset)
    v_ac = v_signal - v_mean

    # 4. Aplicar ventana (Hann) para reducir el Spectral Leakage
    window = sig.get_window('hann', NUM_SAMPLES)
    v_windowed = v_ac * window

    # Corrección de ganancia por enventanado (Coherent Gain Factor)
    win_gain = np.sum(window) / NUM_SAMPLES
    v_windowed = v_windowed / win_gain

    # 5. Cálculo de la FFT (Unilateral)
    fft_vals = np.fft.rfft(v_windowed) / NUM_SAMPLES
    spectrum_mag = np.abs(fft_vals)
    freq_axis = np.fft.rfftfreq(NUM_SAMPLES, d=1.0 / FS)

    # 6. Identificar el pico fundamental y la potencia
    pico_idx = np.argmax(spectrum_mag)
    pico_freq = freq_axis[pico_idx]

    # Para compensar la fuga residual, integramos la energía en una vecindad (lóbulo principal)
    lobe_margin = 4
    start_bin = max(0, pico_idx - lobe_margin)
    end_bin = min(len(spectrum_mag), pico_idx + lobe_margin + 1)

    # Potencia de la señal fundamental
    p_signal = np.sum(spectrum_mag[start_bin:end_bin] ** 2)

    # Potencia total en el espectro (excluyendo DC)
    p_total = np.sum(spectrum_mag[1:] ** 2)

    # Potencia de Ruido + Distorsión (SINAD / SNR)
    p_noise_distortion = p_total - p_signal
    if p_noise_distortion <= 0:
        p_noise_distortion = 1e-12

    # 7. Cálculo de SNR / SINAD (en dB) y ENOB
    snr_db = 10 * np.log10(p_signal / p_noise_distortion)
    enob = (snr_db - 1.76) / 6.02

    # Imprimir reporte en consola
    print("\n" + "=" * 50)
    print("        RESULTADOS DE LA MEDICIÓN DE ENOB         ")
    print("=" * 50)
    print(f" Tensión Media (Offset DC) : {v_mean:.3f} V")
    print(f" Tensión Eficaz (RMS)      : {v_std:.3f} V")
    print(f" Frecuencia Fundamental    : {pico_freq:.2f} Hz")
    print(f" SNR / SINAD Medido        : {snr_db:.2f} dB")
    print(f" -> ENOB Calculado         : {enob:.2f} bits (de {ADC_BITS} nominales)")
    print("=" * 50 + "\n")

    return freq_axis, spectrum_mag, v_signal, snr_db, enob

# ============================================================================
# GRAFICACIÓN INTERACTIVA
# ============================================================================
def graficar_resultados(freq_axis, spectrum_mag, v_signal, snr_db, enob):
    plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

    # Eje de tiempo
    t = np.arange(NUM_SAMPLES) / FS * 1000.0  # en ms

    # Gráfico 1: Señal Temporal
    ax1.plot(t, v_signal, color='tab:blue', linewidth=1.2, label='Señal Analógica Muestreada')
    ax1.set_title('Señal Capturada en el Tiempo (ADC Raspberry Pi Pico 2)', fontsize=12, fontweight='bold')
    ax1.set_xlabel('Tiempo [ms]')
    ax1.set_ylabel('Tensión [V]')
    ax1.set_ylim([0, 3.3])
    ax1.legend(loc='upper right')

    # Gráfico 2: Espectro de Potencia / Magnitud (FFT)
    # Convertir a escala dB Full-Scale (dBFS)
    spectrum_dbfs = 20 * np.log10(spectrum_mag / (V_REF / 2) + 1e-12)

    ax2.plot(freq_axis, spectrum_dbfs, color='tab:red', linewidth=1.2, label='Espectro FFT (Enventanado Hann)')
    ax2.set_title(f'Espectro en Frecuencia — SNR: {snr_db:.2f} dB | ENOB: {enob:.2f} bits', fontsize=12, fontweight='bold')
    ax2.set_xlabel('Frecuencia [Hz]')
    ax2.set_ylabel('Magnitud [dBFS]')
    ax2.set_ylim([-100, 10])
    ax2.legend(loc='upper right')

    plt.tight_layout()
    plt.show()

# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    ser = abrir_puerto_serie(PORT, BAUD_RATE)
    if ser:
        try:
            # Capturar una ráfaga
            datos = capturar_rafaga(ser)
            ser.close()

            # Procesar y calcular
            freq, spec, v_sig, snr, enob = procesar_y_calcular_enob(datos)

            # Mostrar gráficos
            graficar_resultados(freq, spec, v_sig, snr, enob)

        except KeyboardInterrupt:
            print("\n[-] Proceso interrumpido por el usuario.")
            if ser.is_open:
                ser.close()