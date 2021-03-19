# TweakVec

This is a utility for reconfiguring VEC, the composite video encoder on the
Raspberry Pi.

The default NTSC and PAL modes are enough for most cases where you might want to
output composite video, but the Pi's video encoder is actually capable of much
more than that.

PAL-M was always broken in the official firmware, and things like PAL60 were
never implemented properly, either. The Pi can do both of these, and even SECAM
turned out to be implemented in hardware.

## Why?

The factory NTSC and PAL modes cover most typical cases for a composite output.
So why you might want to use this tool?

* On a display that supports it, PAL60 and/or NTSC 4.43 may produce sharper
  image than regular NTSC, while retaining the 60 Hz 480i or 240p raster
  favoured by retro enthusiasts.
* You may some old sets from e.g France or Russia that only supports SECAM, or
  from Brazil that only supports PAL-M. `tweakvec` lets you revive such sets
  without hardware mods - although the video quality will generally be worse in
  those modes compared to regular PAL or NTSC.
* Even if you don't need any of these special modes, `tweakvec` gives you access
  to some additional settings, such as setting horizontal position of the image,
  and relative horizontal position of luminance and chrominance signals.
* Playing with obsolete tech is fun ;) I personally find SECAM artifacts
  charming, even if they're objectively awful ;)

## Usage

TweakVec requires Python 3.7 and access to sysfs and `/dev/mem` (normally only
available to `root`).

TweakVec will also **not** switch line standards (525-line vs. 625-line, a.k.a.
480i60 vs. 576i50), so please use `config.txt`, `tvservice` or the KMS driver to
configure NTSC (for 525-line / 480i60) or PAL (for 625-line / 576i50) standard
first as a baseline. You can also use the progressive modes for 240p60 or
288p50, respectively - TweakVec will also not touch this setting.

Examples:

### Display current configuration

```
sudo python3 tweakvec.py
```

### Configuring most common video modes

#### 60 Hz / 525-line / 480i / 240p modes

You need to first configure **NTSC** mode (even for PAL-M and PAL60) using
standard OS facilities (e.g. `sdtv_mode=0` in `config.txt` or `tvservice
--sdtvon "NTSC 4:3"`) before running any of these. You can use either
interlaced or progressive mode and this setting will be kept by `tweakvec`.

**NOTE:** These modes (including PAL-M and PAL60) have identical sync
specification as the factory NTSC mode. **If your display doesn't produce an
image that is readable at least in black and white in NTSC mode, it is unlikely
that any of these will work for you.**

```
sudo python3 tweakvec.py --preset NTSC     # same as sdtv_mode=0
sudo python3 tweakvec.py --preset NTSC-J   # same as sdtv_mode=1
sudo python3 tweakvec.py --preset NTSC361  # same as sdtv_mode=3
sudo python3 tweakvec.py --preset NTSC443
sudo python3 tweakvec.py --preset PAL-M
sudo python3 tweakvec.py --preset PAL60
sudo python3 tweakvec.py --preset MONO525  # equivalent to sdtv_mode=8
```

#### 50 Hz / 625-line / 576i / 288p modes

You need to first configure **PAL** mode using standard OS facilities (e.g.
`sdtv_mode=2` in `config.txt` or `tvservice --sdtvon "PAL 4:3"`) before
running any of these. You can configure either interlaced or progressive mode.

**NOTE:** These modes (including SECAM) have identical sync specification as
the factory PAL mode. **If your display doesn't produce an image that is
readable at least in black and white in PAL mode, it is unlikely that any of
these will work for you.**
```
sudo python3 tweakvec.py --preset PAL      # same as sdtv_mode=2
sudo python3 tweakvec.py --preset PAL-N    # same as sdtv_mode=0x42
sudo python3 tweakvec.py --preset SECAM
sudo python3 tweakvec.py --preset MONO625  # equivalent to sdtv_mode=10
```

### Setting individual options

```
# move image 7 pixels right - centers PAL/SECAM image
sudo python3 tweakvec.py --hshift 7

# move chroma channel only, relative to luma
sudo python3 tweakvec.py --chroma-shift -1

# enable/disable sync pulses
sudo python3 tweakvec.py --enable-sync 0
sudo python3 tweakvec.py --enable-sync 1

# custom chroma subcarrier frequency
sudo python3 tweakvec.py --fsc 4429687.5
```

### Combining it all

```
# SECAM with full settings reset, full image shift and chroma shift
sudo python3 tweakvec.py --reset --preset SECAM --hshift 7 --chroma-shift -2
```

Use `sudo python3 tweakvec.py --help` for a full list of possible options.

## PAL60 on RetroPie (interlaced and progressive) - quick setup guide

This seems to be the most common use case for this tool, so I'm attaching
a quick setup guide for it.

**NOTE:** I'll stress this again - **your TV/monitor has to be able to display
NTSC image at least in usable black&white** (don't worry about checkerboard
patterns where colour is supposed to be if you get these). **If that's not the
case, PAL60 most likely won't work for you, either.**

**NOTE:** You may substitute `PAL60` with `PAL-M`, `NTSC443` or `MONO525` in
the commands below if you're interested in some of those instead.

Before starting, ensure that `git` and Python 3.7 or newer are installed on the
machine. Current RetroPie images include these by default.

1. Configure your installation to generally use NTSC for everything - use
   `sdtv_mode=0` or `sdtv_mode=0x10` in `config.txt`, and always use `NTSC`
   (never `PAL`) in things like `videomodes.cfg` or `tvservice` invocations
   in `runcommand` scripts.

   Note that RetroPie is configured for NTSC by default.

2. Download `tweakvec` onto your machine. The recommended steps are:

   1. Switch to terminal by pressing Alt+F4 in Emulation Station, or `ssh`
      onto your Pi. Verify that you're in the home directory (on a default
      installation, the prompt should read `pi@retropie:~ $`).

   2. Type `git clone https://github.com/kFYatek/tweakvec`.

      This will download `tweakvec` to `/home/pi/tweakvec`

3. Edit `/opt/retropie/configs/all/autostart.sh`. You can either use:
   *Configuration Editor -> Advanced Configuration -> Manually edit global
   configs -> all/autostart.sh*, or any editor of your choice.

   * Add `sudo python3 /home/pi/tweakvec/tweakvec.py --preset PAL60` at the
     beginning of this file.

4. If you are using custom scripts (e.g. `runcommand-onstart.sh`) that invoke
   `tvservice`, you will need to repeat the above command after each such call.

   * Example set of commands for switching to progressive PAL60:

     `tvservice -c "NTSC 4:3 P"; sudo python3 /home/pi/tweakvec/tweakvec.py --preset PAL60; fbset -depth 8; fbset -depth 32; tvservice -s`

     To return to interlaced mode, use the same command, but with `"NTSC 4:3"`
     instead of `"NTSC 4:3 P"`.

Enjoy! ;)

## What can't it do?

It seems that the VEC is hard-wired to only support the 525-line and 625-line
systems and will not deviate too much from their sync patterns. So sadly, no
reviving of British 405-line or French 819-line sets :(

It is also not possible to configure NTSC-style color for 625-line mode or
SECAM in the 525-line one. You can use PAL for both, but no NTSC50 or SECAM60
for you :(

I also did not find a way to generate a continuous signal without the blanking
periods (you can disable sync pulses, but blanking will still occur).
