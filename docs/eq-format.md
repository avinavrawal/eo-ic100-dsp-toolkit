# Internal EQ format

Static analysis of Samsung firmware 0.23 identified an internal hardware/DSP EQ table at:

```text
0x1E4C4
```

Related firmware strings included:

```text
cfg_hw_aud_eq_band_settings
iir_coefs_generate
hw_codec_iir_get_cfg
hw_codec_iir_set_cfg
audio_eq_set_cfg
usb_audio_set_eq
```

## Table layout

```c
float    gain_l_db;
float    gain_r_db;
uint32_t filter_count;

struct eq_filter {
    uint32_t type;
    float    gain_db;
    float    frequency_hz;
    float    q;
};
```

Eight filter slots fit in the observed region.

Likely type mapping:

```text
0  low shelf
1  peak
2  high shelf
3  low pass
4  high pass
```

## Stock Samsung 0.23 table

```text
global gain L/R  0.0 dB
filter count     2

1: Peak  -2.0 dB   220 Hz   Q 0.6
2: Peak  -2.0 dB  9000 Hz   Q 8.0
```

## Included Diamond8 preset

The tested modified build uses eight internal filters plus a global gain. See `patcher/presets/diamond8.json`.

It is a tested project preset, not a manufacturer-provided tuning.
