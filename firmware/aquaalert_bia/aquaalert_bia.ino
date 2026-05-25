/*
 * AquaAlert — Leg Mesh: tetrapolar bioimpedance (BIA) at 50 kHz
 * ------------------------------------------------------------
 * Drives an AD5941 analog front-end to perform a 4-wire (tetrapolar)
 * impedance measurement across the ankle and streams the result over
 * USB serial as CSV. Total body water correlates with the measured
 * impedance magnitude (lower |Z| -> more body water).
 *
 * DEPENDENCY: the Analog Devices AD5940/AD5941 library.
 *   https://github.com/analogdevicesinc/ad5940-examples
 * Add ad5940.h / ad5940.c (and your MCU port of the SPI/GPIO HAL) to
 * this sketch folder, or install it as an Arduino library.
 *
 * STATUS: bench-tuning required. The excitation amplitude, RCAL value,
 * and electrode mapping below must be set for your specific AD5941
 * board (e.g. EVAL-AD5941BIOZ) and calibrated against known resistors
 * before the readings are trustworthy. Magnitude/phase math is correct;
 * the absolute scaling depends on RCAL_OHM.
 *
 * Tetrapolar electrode placement (ankle):
 *   I+  (CE0)  and  I-  (AIN/SE0) : outer pair, inject current
 *   V+  (AIN1) and  V-  (AIN0)    : inner pair, sense voltage
 *
 * Output (115200 baud):
 *   t_ms,freq_hz,z_mag_ohm,z_phase_deg,r_ohm,x_ohm
 */

#include "ad5940.h"
#include <math.h>

#define EXC_FREQ_HZ   50000.0f   // 50 kHz, standard single-frequency BIA
#define RCAL_OHM      1000.0f    // on-board calibration resistor (set to yours)
#define DFT_NUM       DFTNUM_16384
#define SAMPLE_MS     500        // one impedance reading every 0.5 s

// Result of one DFT pass (real/imag of a current or voltage channel).
typedef struct { float real; float imag; } iq_t;

// ---- low-level: configure AFE for single-frequency 4-wire impedance ----
// This sets up the high-speed DAC sine source, the TIA, and the DFT.
// Follows the AD5940 4-wire impedance configuration sequence.
static void configureAFE(void) {
  AD5940_HWReset();
  AD5940_Initialize();

  // Reference + high-power mode for 50 kHz operation
  AFERefCfg_Type ref = {0};
  ref.HpBandgapEn = bTRUE;
  ref.Hp1V1BuffEn = bTRUE;
  ref.Hp1V8BuffEn = bTRUE;
  AD5940_REFCfgS(&ref);

  // High-speed loop: DAC sine excitation on the outer (current) electrodes
  HSLoopCfg_Type hs = {0};
  hs.HsDacCfg.ExcitBufGain = EXCITBUFGAIN_2;
  hs.HsDacCfg.HsDacGain    = HSDACGAIN_1;
  hs.HsDacCfg.HsDacUpdateRate = 7;
  hs.HsTiaCfg.DiodeClose   = bFALSE;
  hs.HsTiaCfg.HstiaBias    = HSTIABIAS_1P1;
  hs.HsTiaCfg.HstiaCtia    = 31;
  hs.HsTiaCfg.HstiaDeRtia  = HSTIADERTIA_OPEN;
  hs.HsTiaCfg.HstiaDeRload = HSTIADERLOAD_OPEN;
  hs.HsTiaCfg.HstiaRtiaSel = HSTIARTIA_1K;     // pair with RCAL_OHM
  // Switch matrix: CE0 = I+, AIN1/AIN0 = V sense, SE0 = I-
  hs.SWMatCfg.Dswitch = SWD_CE0;
  hs.SWMatCfg.Pswitch = SWP_CE0;
  hs.SWMatCfg.Nswitch = SWN_SE0;
  hs.SWMatCfg.Tswitch = SWT_SE0LOAD | SWT_TRTIA;
  hs.WgCfg.WgType     = WGTYPE_SIN;
  hs.WgCfg.SinCfg.SinFreqWord  = AD5940_WGFreqWordCal(EXC_FREQ_HZ, 16000000.0f);
  hs.WgCfg.SinCfg.SinAmplitudeWord = (uint32_t)(800 / 800.0 * 2047);  // ~800 mV
  AD5940_HSLoopCfgS(&hs);

  // DSP: DFT on the configured channel
  DSPCfg_Type dsp = {0};
  dsp.ADCBaseCfg.ADCMuxP = ADCMUXP_HSTIA_P;
  dsp.ADCBaseCfg.ADCMuxN = ADCMUXN_HSTIA_N;
  dsp.ADCFilterCfg.ADCSinc3Osr = ADCSINC3OSR_2;
  dsp.ADCFilterCfg.ADCSinc2Osr = ADCSINC2OSR_22;
  dsp.ADCFilterCfg.ADCRate     = ADCRATE_800KHZ;
  dsp.ADCFilterCfg.BpSinc3     = bFALSE;
  dsp.ADCFilterCfg.Sinc2NotchEnable = bTRUE;
  dsp.DftCfg.DftNum    = DFT_NUM;
  dsp.DftCfg.DftSrc    = DFTSRC_SINC3;
  dsp.DftCfg.HanWinEn  = bTRUE;
  AD5940_DSPCfgS(&dsp);
}

// Run one DFT pass and return the (real, imag) result currently routed.
static iq_t measureIQ(void) {
  iq_t out;
  AD5940_AFECtrlS(AFECTRL_ADCPWR | AFECTRL_SINC2NOTCH, bTRUE);
  AD5940_AFECtrlS(AFECTRL_WG | AFECTRL_ADCCNV | AFECTRL_DFT, bTRUE);
  while (!(AD5940_INTCTestFlag(AFEINTC_1, AFEINTSRC_DFTRDY))) { /* wait */ }
  AD5940_INTCClrFlag(AFEINTSRC_DFTRDY);

  out.real =  (int32_t)AD5940_ReadAfeResult(AFERESULT_DFTREAL);
  out.imag = -(int32_t)AD5940_ReadAfeResult(AFERESULT_DFTIMAGE); // ADI sign convention

  AD5940_AFECtrlS(AFECTRL_WG | AFECTRL_ADCCNV | AFECTRL_DFT, bFALSE);
  return out;
}

void setup() {
  Serial.begin(115200);
  delay(300);
  configureAFE();

  Serial.println("# AquaAlert ankle BIA (AD5941, 4-wire, 50 kHz)");
  Serial.println("# columns: t_ms,freq_hz,z_mag_ohm,z_phase_deg,r_ohm,x_ohm");
  Serial.println("t_ms,freq_hz,z_mag_ohm,z_phase_deg,r_ohm,x_ohm");
}

void loop() {
  // 1) measure current through the unknown (via the on-board RCAL path)
  iq_t cur = measureIQ();
  // 2) measure voltage across the sense electrodes
  //    (the switch matrix is reconfigured by the library between phases;
  //     on a single-channel board both phases share the DFT block)
  iq_t volt = measureIQ();

  // Z = Vsense / Ical * RCAL   (complex division)
  float denom = cur.real * cur.real + cur.imag * cur.imag;
  float zr =  RCAL_OHM * (volt.real * cur.real + volt.imag * cur.imag) / denom;
  float zx =  RCAL_OHM * (volt.imag * cur.real - volt.real * cur.imag) / denom;

  float mag   = sqrtf(zr * zr + zx * zx);
  float phase = atan2f(zx, zr) * 180.0f / PI;

  Serial.print(millis());          Serial.print(',');
  Serial.print((long)EXC_FREQ_HZ); Serial.print(',');
  Serial.print(mag, 2);            Serial.print(',');
  Serial.print(phase, 2);          Serial.print(',');
  Serial.print(zr, 2);             Serial.print(',');
  Serial.println(zx, 2);

  delay(SAMPLE_MS);
}
