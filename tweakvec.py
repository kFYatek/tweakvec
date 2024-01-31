#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import collections
import contextlib
import copy
import ctypes
import dataclasses
import enum
import mmap
import os
import sys
import typing

if getattr(typing, 'Annotated', None) is None:
    # Python 3.8 or older
    class _AnnotatedAlias(typing._GenericAlias, _root=True):
        def __init__(self, origin, metadata):
            super().__init__(origin, origin)
            self.__metadata__ = metadata


    class Annotated:
        __slots__ = ()

        def __class_getitem__(cls, params):
            return _AnnotatedAlias(params[0], tuple(params[1:]))


    typing._AnnotatedAlias = _AnnotatedAlias
    typing.Annotated = Annotated

DEVICETREE_BASE = '/sys/firmware/devicetree/base'

ArmMemoryRange = collections.namedtuple('ArmMemoryRange', ['child_address', 'parent_address', 'size'])


class VideoCoreModel(enum.Enum):
    VIDEOCORE4 = enum.auto()
    VIDEOCORE6 = enum.auto()
    VIDEOCORE7 = enum.auto()


class ArmMemoryMapper:
    @classmethod
    def read_size(cls, path):
        with open(path, 'rb') as f:
            return 4 * int.from_bytes(f.read(), 'big')

    @classmethod
    def read_ranges(cls, devpath):
        child_address_size = cls.read_size(os.path.join(devpath, '#address-cells'))
        parent_address_size = cls.read_size(os.path.join(os.path.dirname(devpath), '#address-cells'))
        size_size = cls.read_size(os.path.join(devpath, '#size-cells'))
        entry_size = child_address_size + parent_address_size + size_size

        with open(os.path.join(devpath, 'ranges'), 'rb') as f:
            ranges_property = f.read()

        ranges = set()

        offset = 0
        while offset < len(ranges_property):
            entry = ranges_property[offset:offset + entry_size]
            offset += entry_size

            child_address = int.from_bytes(entry[0:child_address_size], 'big')
            parent_address = int.from_bytes(entry[child_address_size:child_address_size + parent_address_size], 'big')
            size = int.from_bytes(entry[child_address_size + parent_address_size:], 'big')

            ranges.add(ArmMemoryRange(child_address=child_address, parent_address=parent_address, size=size))

        return ranges

    @classmethod
    def get_symbol_path(cls, symbol):
        with open(os.path.join(DEVICETREE_BASE, '__symbols__', symbol), 'r') as f:
            return DEVICETREE_BASE + f.read().replace('\0', '')

    @classmethod
    def get_address(cls, devpath):
        address_size = cls.read_size(os.path.join(os.path.dirname(devpath), '#address-cells'))
        with open(os.path.join(devpath, 'reg'), 'rb') as f:
            return int.from_bytes(f.read(address_size), 'big')

    def __init__(self):
        super().__init__()
        self.ranges = self.read_ranges(os.path.join(DEVICETREE_BASE, 'soc'))

    def map_address(self, physical_address):
        for range in self.ranges:
            if range.child_address <= physical_address < range.child_address + range.size:
                return physical_address - range.child_address + range.parent_address

    def map_path_address(self, devpath):
        return self.map_address(self.get_address(devpath))

    def map_symbol_address(self, symbol):
        return self.map_path_address(self.get_symbol_path(symbol))


class MemoryMappedAccessor(contextlib.closing):
    def __init__(self, memfd, address, length=0x1000):
        super().__init__(self)
        self.memory = mmap.mmap(memfd, length=length, offset=address)

    def close(self):
        self.memory.close()

    class Register:
        def __init__(self, offset, type=ctypes.c_uint32):
            self._offset = offset
            self._type = type

        def __get__(self, instance, owner):
            return self._type.from_buffer(instance.memory, self._offset).value

        def __set__(self, instance, value):
            self._type.from_buffer(instance.memory, self._offset).value = value


class VecPixelValveAccessor(MemoryMappedAccessor):
    def __init__(self, memfd, mapper: ArmMemoryMapper):
        try:
            path = mapper.get_symbol_path('pixelvalve3')
            self.model = VideoCoreModel.VIDEOCORE6
        except FileNotFoundError:
            try:
                path = mapper.get_symbol_path('pixelvalve2')
                self.model = VideoCoreModel.VIDEOCORE4
            except FileNotFoundError:
                path = mapper.get_symbol_path('pixelvalve1')
                self.model = VideoCoreModel.VIDEOCORE7

        super().__init__(memfd, mapper.map_path_address(path))

    control = MemoryMappedAccessor.Register(0x00)
    v_control = MemoryMappedAccessor.Register(0x04)
    vsyncd_even = MemoryMappedAccessor.Register(0x08)
    horza = MemoryMappedAccessor.Register(0x0c)
    horzb = MemoryMappedAccessor.Register(0x10)
    verta = MemoryMappedAccessor.Register(0x14)
    vertb = MemoryMappedAccessor.Register(0x18)
    verta_even = MemoryMappedAccessor.Register(0x1c)
    vertb_even = MemoryMappedAccessor.Register(0x20)
    inten = MemoryMappedAccessor.Register(0x24)
    intstat = MemoryMappedAccessor.Register(0x28)
    stat = MemoryMappedAccessor.Register(0x2c)
    hact_act = MemoryMappedAccessor.Register(0x30)


class VecAccessor(MemoryMappedAccessor):
    def __init__(self, memfd, mapper: ArmMemoryMapper, model: VideoCoreModel):
        # We should normally use address = mapper.map_symbol_address('vec'),
        # but on some Raspberry Pi 4 kernels this address is wrong
        if model == VideoCoreModel.VIDEOCORE6:
            super().__init__(memfd, mapper.map_address(0x7ec13000))
        else:
            super().__init__(memfd, mapper.map_symbol_address('vec'))

    wse_reset = MemoryMappedAccessor.Register(0xc0)
    wse_control = MemoryMappedAccessor.Register(0xc4)
    wse_wss_data = MemoryMappedAccessor.Register(0xc8)
    wse_vps_data1 = MemoryMappedAccessor.Register(0xcc)
    wse_vps_control = MemoryMappedAccessor.Register(0xd0)

    revid = MemoryMappedAccessor.Register(0x100)
    config0 = MemoryMappedAccessor.Register(0x104)
    schph = MemoryMappedAccessor.Register(0x108)
    soft_reset = MemoryMappedAccessor.Register(0x10c)

    clmp0_start = MemoryMappedAccessor.Register(0x144)
    clmp0_end = MemoryMappedAccessor.Register(0x148)

    freq3_2 = MemoryMappedAccessor.Register(0x180)
    freq1_0 = MemoryMappedAccessor.Register(0x184)
    config1 = MemoryMappedAccessor.Register(0x188)
    config2 = MemoryMappedAccessor.Register(0x18c)
    interrupt_control = MemoryMappedAccessor.Register(0x190)
    interrupt_status = MemoryMappedAccessor.Register(0x194)
    fcw_secam_b = MemoryMappedAccessor.Register(0x198)
    secam_gain_val = MemoryMappedAccessor.Register(0x19c)
    config3 = MemoryMappedAccessor.Register(0x1a0)

    status0 = MemoryMappedAccessor.Register(0x200)
    mask0 = MemoryMappedAccessor.Register(0x204)
    cfg = MemoryMappedAccessor.Register(0x208)
    dac_test = MemoryMappedAccessor.Register(0x20c)
    dac_config = MemoryMappedAccessor.Register(0x210)
    dac_misc = MemoryMappedAccessor.Register(0x214)


class FrequencyPreset:
    NTSC = 3579545.0 + 5.0 / 11.0
    PAL = 4433618.75
    PAL_M = 3575611.0 + 127.0 / 143.0
    PAL_N = 3582056.25
    SECAM_DR = 4406250.0
    SECAM_DB = 4250000.0


class LineStandard(enum.Enum):
    LINES_525 = enum.auto()
    LINES_625 = enum.auto()


class VecVideoStandard(enum.Enum):
    NTSC = 0
    PAL = 1
    PAL_M = 2
    PAL_N = 3
    SECAM = 0x00200000

    @property
    def help(self):
        return {
            self.NTSC: f'525 lines, QAM; default subcarrier frequency: {FrequencyPreset.NTSC} Hz (227.5 * fH)',
            self.PAL: '625 lines, QAM with phase alternation; ' \
                      + f'default subcarrier frequency: {FrequencyPreset.PAL} Hz (283.7516 * fH)',
            self.PAL_M: '525 lines, QAM with phase alternation; ' \
                        + f'default subcarrier frequency: {FrequencyPreset.PAL_M} Hz (227.25 * fH)',
            self.PAL_N: '625 lines, QAM with phase alternation; default subcarrier frequency: ' \
                        + f'{FrequencyPreset.PAL_N} Hz (229.2516 * fH), otherwise identical to regular PAL',
            self.SECAM: f'625 lines, FM sequentially alternating between Dr (default fSC = {FrequencyPreset.SECAM_DR}' \
                        + f' Hz = 282 * fH) and Db (default fSC = {FrequencyPreset.SECAM_DB} Hz = 272 * fH)'
        }[self]

    @classmethod
    def mask(cls):
        result = 0
        for member in cls:
            result |= member.value
        return result

    def line_standard(self):
        if isinstance(self, VecVideoStandard):
            value = self.value
        else:
            value = self
        if value == VecVideoStandard.NTSC.value or value == VecVideoStandard.PAL_M.value:
            return LineStandard.LINES_525
        else:
            return LineStandard.LINES_625


class Config0:
    STD_MASK = VecVideoStandard.mask()
    RAMPEN = 0x00000008  # shows horizontal gradient
    YCDELAY = 0x00000010  # shifts image about half a pixel to the right
    # 0x00000020 seems to add some weird tint in SECAM mode???
    PDEN = 0x00000040  # 525-line pedestal
    CHRDIS = 0x00000080  # chroma disable (encodes only the Y channel, but with color burst intact)
    BURDIS = 0x00000100  # colorburst disable (chroma is still encoded in the visible portion)
    SYNCDIS = 0x00000200  # sync disable
    CBURST_GAIN_MASK = 0x00006000
    CHROMA_GAIN_MASK = 0x00030000
    # 0x00400000 reduces saturation of SECAM signal???
    CDEL_MASK = 0x03000000  # chroma delay (in pixels?)
    YDEL_MASK = 0x1c000000  # luma delay (in pixels?)


class OutputMode(enum.Enum):
    C_Y_CVBS = 0x00000000
    CVBS_Y_C = 0x00000400
    PR_Y_PB = 0x00000800
    RGB = 0x00001000
    Y_C_CVBS = 0x00001400
    C_CVBS_Y = 0x00001800
    C_CVBS_CVBS = 0x00001c00

    @classmethod
    def mask(cls):
        result = 0
        for member in cls:
            result |= member.value
        return result


class Config1:
    CUSTOM_FREQ = 0x00000001  # enable custom chroma subcarrier frequency
    LUMADIS = 0x00000004  # luma disable
    YCBCR_IN = 0x00000040  # treat RGB as YCbCr
    OUTPUT_MODE_MASK = OutputMode.mask()
    CBAR_EN = 0x00010000  # enables color bars output
    RGB219 = 0x00020000  # limited range on input?


class Config2:
    SYNC_ADJ_MASK = 0x00007000
    PROG_SCAN = 0x00008000


class Config3:
    HORIZ_LEN_MPEG1_SIF = 0x00000001
    NON_LINEAR = 0x00000002


class Cfg:
    ENABLE = 0x00000002
    VEC_EN = 0x00000008
    SG_EN = 0x00000010
    SG_MODE_MASK = 0x00000060


class PictureMode(enum.Enum):
    NORMAL = enum.auto()
    RAMP = enum.auto()
    COLORBARS = enum.auto()
    SIGNAL1 = enum.auto()
    SIGNAL2 = enum.auto()
    SIGNAL3 = enum.auto()
    SIGNAL4 = enum.auto()


@dataclasses.dataclass
class Configuration:
    standard: typing.Annotated[typing.Optional[VecVideoStandard], 'Base video standard'] = None
    output: typing.Annotated[typing.Optional[OutputMode], 'Output mapping mode'] = None
    picture: typing.Annotated[typing.Optional[PictureMode], 'Picture display mode'] = None
    hshift: typing.Annotated[typing.Optional[float], 'Image horizontal shift (in pixels)'] = None
    fsc: typing.Annotated[
        typing.Optional[float],
        'Subcarrier frequency in Hz (for SECAM: Dr center frequency); non-positive value resets to default'] = None
    secam_fb: typing.Annotated[
        typing.Optional[float], 'Db center frequency for SECAM in Hz; non-positive value resets to default'] = None
    pedestal: typing.Annotated[typing.Optional[bool], 'Enable pedestal (525-line modes only)'] = None
    enable_luma: typing.Annotated[typing.Optional[bool], 'Enable luminance output'] = None
    enable_chroma: typing.Annotated[
        typing.Optional[bool],
        'Enable chrominance output (note: for SECAM, unmodulated subcarrier for gray is output when disabled)'] = None
    enable_burst: typing.Annotated[typing.Optional[bool], 'Enable color burst (note: ignored for SECAM)'] = None
    enable_sync: typing.Annotated[typing.Optional[bool], 'Enable synchronization pulses'] = None
    burst_gain: typing.Annotated[typing.Optional[int], 'Color burst gain setting'] = None
    chroma_gain: typing.Annotated[typing.Optional[int], 'Chrominance signal gain setting'] = None
    chroma_shift: typing.Annotated[typing.Optional[int], 'Chrominance signal horizontal shift'] = None
    ycbcr_input: typing.Annotated[typing.Optional[bool], 'Treat data from PixelValve as YCbCr instead of RGB'] = None
    limited_range: typing.Annotated[typing.Optional[bool], 'Treat data from PixelValve as RGB219 limited range'] = None
    sync_adj: typing.Annotated[typing.Optional[int], 'Synchronization pulses adjustment'] = None
    horiz_mask_sif: typing.Annotated[typing.Optional[bool], 'Limit active image width to MPEG-1 SIF standard'] = None
    horiz_mask_linear: typing.Annotated[typing.Optional[bool], 'Use linear ramp on edges of active image width'] = None


class Preset(Configuration):
    def __init__(self, *, help=None, **kwargs):
        super().__init__(output=OutputMode.C_CVBS_CVBS,
                         picture=PictureMode.NORMAL,
                         fsc=0.0,
                         secam_fb=0.0,
                         pedestal=False,
                         enable_luma=True,
                         enable_chroma=True,
                         enable_burst=True,
                         enable_sync=True,
                         burst_gain=0,
                         chroma_gain=0,
                         chroma_shift=0,
                         ycbcr_input=False,
                         limited_range=False,
                         sync_adj=0,
                         horiz_mask_sif=False,
                         horiz_mask_linear=False)
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.help = help


Preset.NTSC = Preset(standard=VecVideoStandard.NTSC, pedestal=True,
                     help='NTSC-M (525 lines; North America, South Korea, Taiwan, Philippines etc.)')
Preset.NTSC_J = Preset(standard=VecVideoStandard.NTSC,
                       help='NTSC-J (525 lines; Japan - no pedestal)')
Preset.NTSC361 = Preset(standard=VecVideoStandard.NTSC, fsc=3610402.169405,
                        help='NTSC 3.61 (525 lines; broken fake "PAL-M" generated by sdtv_mode=3)')
Preset.NTSC443 = Preset(standard=VecVideoStandard.NTSC, pedestal=True, fsc=FrequencyPreset.PAL,
                        help='NTSC 4.43 (525 lines; NTSC playback on PAL VCRs etc.)')
Preset.PAL = Preset(standard=VecVideoStandard.PAL,
                    help='PAL-B/D/G/H/I/K (625 lines; Western Europe, South Asia, Australia, etc.)')
Preset.PAL_M = Preset(standard=VecVideoStandard.PAL_M,
                      help='PAL-M (525 lines; Brazil)')
Preset.PAL_N = Preset(standard=VecVideoStandard.PAL_N,
                      help='PAL-N (625 lines; Argentina, Paraguay, Uruguay)')
Preset.PAL60 = Preset(standard=VecVideoStandard.PAL_M, fsc=FrequencyPreset.PAL,
                      help='PAL60 (525 lines format used by PAL video game consoles etc.)')
Preset.SECAM = Preset(standard=VecVideoStandard.SECAM,
                      help='SECAM IIIb (625 lines; France, Russia, etc.)')
Preset.MONO525 = Preset(standard=VecVideoStandard.NTSC, pedestal=True, enable_chroma=False, enable_burst=False,
                        help='525 lines ("NTSC") black & white')
Preset.MONO625 = Preset(standard=VecVideoStandard.PAL, enable_chroma=False, enable_burst=False,
                        help='625 lines ("PAL/SECAM") black & white')


class TweakVecInvalidArgument(ValueError):
    pass


class TweakVecContext(contextlib.closing):
    def __init__(self):
        super().__init__(self)
        self.memfd = None
        self.pv = None
        self.vec = None
        self.mapper = ArmMemoryMapper()
        try:
            self.memfd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
            self.pv = VecPixelValveAccessor(self.memfd, self.mapper)
            self.vec = VecAccessor(self.memfd, self.mapper, self.pv.model)
        except BaseException:
            self.close()
            raise

    def close(self):
        try:
            if self.vec is not None:
                self.vec.close()
        finally:
            try:
                if self.pv is not None:
                    self.pv.close()
            finally:
                if self.memfd is not None:
                    os.close(self.memfd)

    def current_config(self):
        def get_masked_int(variable, mask):
            result = variable & mask
            if result != 0:
                while mask & 1 == 0:
                    result >>= 1
                    mask >>= 1
            return result

        config0 = self.vec.config0
        freq = (self.vec.freq3_2 << 16) | (self.vec.freq1_0 & 0xffff)
        config1 = self.vec.config1
        config2 = self.vec.config2
        secam_b_freq = self.vec.fcw_secam_b
        config3 = self.vec.config3
        cfg = self.vec.cfg
        horza = self.pv.horza

        if cfg & Cfg.SG_EN:
            if cfg & Cfg.SG_MODE_MASK == 0x00:
                picture = PictureMode.SIGNAL1
            elif cfg & Cfg.SG_MODE_MASK == 0x20:
                picture = PictureMode.SIGNAL2
            elif cfg & Cfg.SG_MODE_MASK == 0x40:
                picture = PictureMode.SIGNAL3
            else:  # if cfg & Cfg.SG_MODE_MASK == 0x60:
                picture = PictureMode.SIGNAL4
        elif config0 & Config0.RAMPEN:
            picture = PictureMode.RAMP
        elif config1 & Config1.CBAR_EN:
            picture = PictureMode.COLORBARS
        else:
            picture = PictureMode.NORMAL

        standard = VecVideoStandard(config0 & Config0.STD_MASK)
        if config1 & Config1.CUSTOM_FREQ or standard is VecVideoStandard.SECAM:
            freq = (freq * 27000000.0) / (2 ** 32)
        else:
            freq = getattr(FrequencyPreset, standard.name)

        return Configuration(standard=standard,
                             output=OutputMode(config1 & Config1.OUTPUT_MODE_MASK),
                             picture=picture,
                             hshift=(horza >> 16) - 60 + (0.5 if config0 & Config0.YCDELAY else 0.0),
                             fsc=freq,
                             secam_fb=(secam_b_freq * 27000000.0) / (2 ** 32),
                             pedestal=bool(config0 & Config0.PDEN),
                             enable_luma=not bool(config1 & Config1.LUMADIS),
                             enable_chroma=not bool(config0 & Config0.CHRDIS),
                             enable_burst=not bool(config0 & Config0.BURDIS),
                             enable_sync=not bool(config0 & Config0.SYNCDIS),
                             burst_gain=get_masked_int(config0, Config0.CBURST_GAIN_MASK),
                             chroma_gain=get_masked_int(config0, Config0.CHROMA_GAIN_MASK),
                             chroma_shift=get_masked_int(config0, Config0.CDEL_MASK) \
                                          - get_masked_int(config0, Config0.YDEL_MASK),
                             ycbcr_input=bool(config1 & Config1.YCBCR_IN),
                             limited_range=bool(config1 & Config1.RGB219),
                             sync_adj=get_masked_int(config2, Config2.SYNC_ADJ_MASK),
                             horiz_mask_sif=bool(config3 & Config3.HORIZ_LEN_MPEG1_SIF),
                             horiz_mask_linear=bool(config3 & Config3.NON_LINEAR))

    def apply(self, config: Configuration, force=False):
        def set_masked_int(name, variable, mask, value):
            assert mask > 0
            variable = variable & ~mask

            shift = 0
            while mask & 1 == 0:
                shift += 1
                mask //= 2
            bits = 0
            while mask & 1 != 0:
                bits += 1
                mask //= 2

            if value < 0 or value >= 2 ** bits:
                raise TweakVecInvalidArgument(f'Invalid value for {name}: {value}; valid values are 0..{2 ** bits - 1}')

            return variable | (value << shift)

        if not force and (self.pv.control & 0x0000000c) != 0x00000008:
            raise TweakVecInvalidArgument('Cowardly refusing to reconfigure VEC while it is not in use, '
                                          + 'use --force to override')

        ycdelay = None
        hshift = None
        if config.hshift is not None:
            ycdelay = False
            tmp = int(config.hshift * 2.0 + 0.5)
            if tmp % 2 == 1:
                ycdelay = True
                tmp -= 1
            hshift = tmp // 2

        config0 = None
        if any(val is not None for val in (config.standard, config.picture, ycdelay, config.pedestal,
                                           config.enable_chroma, config.enable_burst, config.enable_sync,
                                           config.burst_gain, config.chroma_gain, config.chroma_shift)):
            config0 = self.vec.config0

            if config.standard is not None:
                if not force and config.standard.line_standard() \
                        != VecVideoStandard.line_standard(config0 & Config0.STD_MASK):
                    raise TweakVecInvalidArgument('Cowardly refusing to reconfigure the line standard. '
                                                  + 'Please switch modes using config.txt, tvservice or KMS first, '
                                                  + 'or use --force to override (it WILL result in garbled image)')
                config0 = (config0 & ~Config0.STD_MASK) | config.standard.value

            if config.picture is not None:
                config0 = config0 & ~Config0.RAMPEN
                if config.picture == PictureMode.RAMP:
                    config0 = config0 | Config0.RAMPEN

            if ycdelay is not None:
                config0 = config0 & ~Config0.YCDELAY
                if ycdelay:
                    config0 = config0 | Config0.YCDELAY

            if config.pedestal is not None:
                config0 = config0 & ~Config0.PDEN
                if config.pedestal:
                    if not force and VecVideoStandard.line_standard(
                            config0 & Config0.STD_MASK) != LineStandard.LINES_525:
                        raise TweakVecInvalidArgument('Pedestal is supported in 525-line modes only. '
                                                      + 'You may use --force to override (it will be ignored)')
                    config0 = config0 | Config0.PDEN

            if config.enable_chroma is not None:
                config0 = config0 & ~Config0.CHRDIS
                if not config.enable_chroma:
                    config0 = config0 | Config0.CHRDIS

            if config.enable_burst is not None:
                config0 = config0 & ~Config0.BURDIS
                if not config.enable_burst:
                    config0 = config0 | Config0.BURDIS

            if config.enable_sync is not None:
                config0 = config0 & ~Config0.SYNCDIS
                if not config.enable_sync:
                    config0 = config0 | Config0.SYNCDIS

            if config.burst_gain is not None:
                config0 = set_masked_int('burst_gain', config0, Config0.CBURST_GAIN_MASK, config.burst_gain)

            if config.chroma_gain is not None:
                config0 = set_masked_int('chroma_gain', config0, Config0.CHROMA_GAIN_MASK, config.chroma_gain)

            if config.chroma_shift is not None:
                luma_shift = 0
                chroma_shift = 0
                if config.chroma_shift > 0:
                    chroma_shift = config.chroma_shift
                elif config.chroma_shift < 0:
                    luma_shift = -config.chroma_shift
                config0 = set_masked_int('positive chroma_shift', config0, Config0.CDEL_MASK, chroma_shift)
                config0 = set_masked_int('negative chroma_shift', config0, Config0.YDEL_MASK, luma_shift)

        freq = None
        if config.fsc is not None:
            freq = config.fsc
            if freq <= 0.0:
                freq = FrequencyPreset.SECAM_DR
            freq = int((freq * 2 ** 32) / 27000000.0 + 0.5)
            if freq >= 2 ** 32:
                raise TweakVecInvalidArgument('fsc must be less than 27000000 Hz')

        config1 = None
        if any(val is not None for val in (config.output, config.picture, config.fsc, config.enable_luma,
                                           config.ycbcr_input, config.limited_range)):
            config1 = self.vec.config1

            if config.output is not None:
                config1 = config1 & ~Config1.OUTPUT_MODE_MASK
                config1 = config1 | config.output.value

            if config.picture is not None:
                config1 = config1 & ~Config1.CBAR_EN
                if config.picture == PictureMode.COLORBARS:
                    config1 = config1 | Config1.CBAR_EN

            if config.fsc is not None:
                config1 = config1 & ~Config1.CUSTOM_FREQ
                if config.fsc > 0.0:
                    config1 = config1 | Config1.CUSTOM_FREQ

            if config.enable_luma is not None:
                config1 = config1 & ~Config1.LUMADIS
                if not config.enable_luma:
                    config1 = config1 | Config1.LUMADIS

            if config.ycbcr_input is not None:
                config1 = config1 & ~Config1.YCBCR_IN
                if config.ycbcr_input:
                    config1 = config1 | Config1.YCBCR_IN

            if config.limited_range is not None:
                config1 = config1 & ~Config1.RGB219
                if config.limited_range:
                    config1 = config1 | Config1.RGB219

        config2 = None
        if config.sync_adj is not None:
            config2 = set_masked_int('sync_adj', self.vec.config2, Config2.SYNC_ADJ_MASK, config.sync_adj)

        secam_b_freq = None
        if config.secam_fb is not None:
            secam_b_freq = config.secam_fb
            if secam_b_freq <= 0.0:
                secam_b_freq = FrequencyPreset.SECAM_DB
            secam_b_freq = int((secam_b_freq * 2 ** 32) / 27000000.0 + 0.5)
            if secam_b_freq < 0 or secam_b_freq >= 2 ** 32:
                raise TweakVecInvalidArgument('secam_fb must be less than 27000000 Hz')

        config3 = None
        if any(val is not None for val in (config.horiz_mask_sif, config.horiz_mask_linear)):
            config3 = self.vec.config3

            if config.horiz_mask_sif is not None:
                config3 = config3 & ~Config3.HORIZ_LEN_MPEG1_SIF
                if config.horiz_mask_sif:
                    config3 = config3 | Config3.HORIZ_LEN_MPEG1_SIF

            if config.horiz_mask_linear is not None:
                config3 = config3 & ~Config3.NON_LINEAR
                if not config.horiz_mask_linear:
                    config3 = config3 | Config3.NON_LINEAR

        cfg = None
        if config.picture is not None:
            if config.picture == PictureMode.SIGNAL1:
                cfg = set_masked_int('sg_mode', Cfg.SG_EN, Cfg.SG_MODE_MASK, 0)
            elif config.picture == PictureMode.SIGNAL2:
                cfg = set_masked_int('sg_mode', Cfg.SG_EN, Cfg.SG_MODE_MASK, 1)
            elif config.picture == PictureMode.SIGNAL3:
                cfg = set_masked_int('sg_mode', Cfg.SG_EN, Cfg.SG_MODE_MASK, 2)
            elif config.picture == PictureMode.SIGNAL4:
                cfg = set_masked_int('sg_mode', Cfg.SG_EN, Cfg.SG_MODE_MASK, 3)
            else:
                cfg = Cfg.ENABLE | Cfg.VEC_EN

        horza = None
        horzb = None
        if hshift is not None:
            horza = self.pv.horza
            horzb = self.pv.horzb
            hbp = horza >> 16
            hsync = horza & 0xffff
            hfp = horzb >> 16
            hactive = horzb & 0xffff
            htotal = hbp + hsync + hfp + hactive

            if htotal == 858:
                # 525-line mode
                hfp = 14
            elif htotal == 864:
                # 625-line mode
                hfp = 20
            else:
                raise TweakVecInvalidArgument(
                    f'PixelValve configured for unknown total horizontal resolution: {htotal}')

            hbp = 60
            hsync = 64
            hactive = 720

            if hshift < -hbp or hshift > hfp:
                raise TweakVecInvalidArgument(f'Invalid value for hshift: {hshift}; valid values are {-hbp}..{hfp}')

            hfp -= hshift
            hbp += hshift

            horza = (hbp << 16) | hsync
            horzb = (hfp << 16) | hactive

        if config0 is not None:
            self.vec.config0 = config0
        if freq is not None:
            self.vec.freq3_2 = freq >> 16
            self.vec.freq1_0 = freq & 0xffff
        if config1 is not None:
            self.vec.config1 = config1
        if config2 is not None:
            self.vec.config2 = config2
        if secam_b_freq is not None:
            self.vec.fcw_secam_b = secam_b_freq
        if config3 is not None:
            self.vec.config3 = config3
        if cfg is not None:
            self.vec.cfg = cfg
        if horza is not None:
            self.pv.horza = horza
        if horzb is not None:
            self.pv.horzb = horzb


def _strtobool(value):
    _MAP = {
        'y': True,
        'yes': True,
        't': True,
        'true': True,
        'on': True,
        '1': True,
        'n': False,
        'no': False,
        'f': False,
        'false': False,
        'off': False,
        '0': False
    }
    try:
        return _MAP[str(value).lower()]
    except KeyError:
        raise ValueError(str(value) + ' is not a valid bool value')


def _parse_args(argv=None):
    class NewlineAwareFormatter(argparse.HelpFormatter):
        def _format_action(self, *args, **kwargs):
            return super()._format_action(*args, **kwargs) + '\n'

        def _split_lines(self, text, width):
            result = []
            for line in text.splitlines():
                if line == '':
                    result.append(line)
                else:
                    result += super()._split_lines(line, width)
            return result

    def store_enum(enum_class):
        class EnumStoreAction(argparse.Action):
            def __call__(self, parser, namespace, values, option_string=None):
                setattr(namespace, self.dest, getattr(enum_class, values.replace('-', '_')))

        return EnumStoreAction

    def enum_choices(enum_class):
        try:
            members = enum_class.__members__
        except AttributeError:
            members = enum_class.__dict__
        return [member.replace('_', '-') for member in members if not member.startswith('_')]

    def add_enum_argument(parser, argname, enum_class, help=None):
        choices = enum_choices(enum_class)
        if help is None:
            help = 'Available settings:'
        else:
            help += '; available settings:'
        for choice in choices:
            help += '\n\n' + choice
            member = getattr(enum_class, choice.replace('-', '_'))
            member_help = getattr(member, 'help', None)
            if member_help is not None:
                help += ' - ' + member_help
        return parser.add_argument(argname, action=store_enum(enum_class), choices=choices,
                                   help=help, metavar=enum_class.__name__.upper())

    parser = argparse.ArgumentParser(description='Tweak settings of the Raspberry Pi composite video encoder',
                                     formatter_class=NewlineAwareFormatter)

    add_enum_argument(
        parser, '--preset', Preset,
        help='Preset of one of common color formats to use before applying individual tweaks')

    parser.add_argument('--reset', action='store_true',
                        help='Reset all settings to defaults before applying anything else')

    parser.add_argument('--force', action='store_true',
                        help='Force applying configuration even if may be dangerous')

    for field in Configuration.__dataclass_fields__.values():
        argname = '--' + field.name.replace('_', '-')
        help = None
        field_type = field.type
        while isinstance(field_type, typing._GenericAlias):
            if help is None:
                metadata = getattr(field_type, '__metadata__', None)
                if metadata is not None and len(metadata) > 0:
                    help = metadata[0]
            field_type = field_type.__args__[0]

        if issubclass(field_type, enum.Enum):
            add_enum_argument(parser, argname, field_type, help)
        else:
            metavar = field_type.__name__.upper()
            if field_type is bool:
                field_type = _strtobool
            parser.add_argument(argname, type=field_type, help=help, metavar=metavar)

    return parser.parse_args(argv)


def _main(argv=None):
    ctx_value = None

    def ctx():
        nonlocal ctx_value
        if ctx_value is None:
            ctx_value = TweakVecContext()
        return ctx_value

    args = _parse_args(argv)

    if not args.reset and not args.force \
            and all(value is None or key in {'reset', 'force'} for key, value in args.__dict__.items()):
        # List current configuration
        current_config = ctx().current_config()
        for field in Configuration.__dataclass_fields__.values():
            print(f'{field.name} = {repr(getattr(current_config, field.name))}')
        return

    # Modify configuration
    try:
        config = Configuration()
        if args.reset and not args.preset is not None:
            args.preset = Preset.__dict__[ctx().current_config().standard.name]
        if args.preset is not None:
            config = copy.copy(args.preset)
        if args.reset:
            config.hshift = 0.0

        args = args.__dict__
        args.pop('reset', None)
        args.pop('preset', None)
        force = args.pop('force', False)
        for key, value in args.items():
            if value is not None:
                setattr(config, key, value)

        ctx().apply(config, force)
    except FileNotFoundError as e:
        sys.stderr.write(f'{e}\nAre you running on a Raspberry Pi?\n')
        return -1
    except PermissionError as e:
        sys.stderr.write(f'{e}\nYou must be root or have access to /dev/mem to run tweakvec\n')
        return -1
    except TweakVecInvalidArgument as e:
        sys.stderr.write(str(e) + '\n')
        return -1


if __name__ == '__main__':
    sys.exit(_main())
