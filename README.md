# TweakVec

This is an utility for reconfiguring VEC, the composite video encoder on the
Raspberry Pi.

The default NTSC and PAL modes are enough for most cases where you might want to
output composite video, but the Pi's video encoder is actually capable of much
more than that.

PAL-M was always broken in the official firmware, and things like PAL60 were
never implemented properly, either. The Pi can do both of these, and even SECAM
turned out to be implemented in hardware.

## Usage

TweakVec requires Python 3.8 and access to sysfs and `/dev/mem` (normally only
available to `root`).

TweakVec will also **not** switch line standards (525-line vs. 625-line, a.k.a.
480i60 vs. 576i50), so please use `config.txt`, `tvservice` or the KMS driver to
configure NTSC (for 525-line / 480i60) or PAL (for 625-line / 576i50) standard
first as a baseline. You can also use the progressive modes for 240p60 or
288p50, respectively - TweakVec will also not touch this setting.

Examples:

### Display current configuration

```
sudo ./tweakvec.py
```

### Configuring most common video modes

```
sudo ./tweakvec.py --preset NTSC
sudo ./tweakvec.py --preset NTSC-J
sudo ./tweakvec.py --preset NTSC361  # this is what sdtv_mode=3 generates
sudo ./tweakvec.py --preset NTSC443
sudo ./tweakvec.py --preset PAL
sudo ./tweakvec.py --preset PAL-M
sudo ./tweakvec.py --preset PAL-N
sudo ./tweakvec.py --preset PAL60
sudo ./tweakvec.py --preset SECAM
sudo ./tweakvec.py --preset MONO525
sudo ./tweakvec.py --preset MONO625
```

### Setting individual options

```
# move image 7 pixels right - centers PAL/SECAM image
sudo ./tweakvec.py --hshift 7

# move chroma channel only, relative to luma
sudo ./tweakvec.py --chroma-shift -1

# enable/disable sync pulses
sudo ./tweakvec.py --enable-sync 0
sudo ./tweakvec.py --enable-sync 1

# custom chroma subcarrier frequency
sudo ./tweakvec.py --fsc 4429687.5
```

### Combining it all

```
# SECAM with full settings reset, full image shift and chroma shift
sudo ./tweakvec.py --reset --preset SECAM --hshift 7 --chroma-shift -2
```

Use `sudo ./tweakvec.py --help` for a full list of possible options.

## What can't it do?

It seems that the VEC is hard-wired to only support the 525-line and 625-line
systems and will not deviate too much from their sync patterns. So sadly, no
reviving of British 405-line or French 819-line sets :(

It is also not possible to configure NTSC-style color for 625-line mode or
SECAM in the 525-line one. You can use PAL for both, but no NTSC50 or SECAM60
for you :(

I also did not find a way to generate a continuous signal without the blanking
periods (you can disable sync pulses, but blanking will still occur).
