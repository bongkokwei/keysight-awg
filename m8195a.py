"""
Keysight M8195A Arbitrary Waveform Generator control class.

Provides a Pythonic interface to the M8195A Rev 2 AWG via SCPI commands
over a raw TCP socket (port 5025).

Requirements:
    pip install numpy

Usage:
    awg = M8195A("192.168.1.10")
    awg.reset()
    awg.dac_mode = "FOUR"
    awg.sample_rate = 64e9
    awg.define_segment(1, 1, 1280, init_value=0)
    awg.load_waveform(1, 1, waveform_array)
    awg.set_output(1, True)
    awg.start(1)
    # ...
    awg.close()
"""

from __future__ import annotations

import logging
import socket
import struct
from typing import Optional, Union

import numpy as np

logger = logging.getLogger(__name__)


class M8195A:
    """Driver for the Keysight M8195A 65 GSa/s Arbitrary Waveform Generator.

    Communicates via raw SCPI-over-TCP on port 5025.  The *host* is the
    IP address of the M9536A embedded controller (or whichever PC is
    running the Soft Front Panel).

    Parameters
    ----------
    host : str
        IP address or hostname of the SCPI server,
        e.g. ``"192.168.1.10"`` or a ``169.254.x.x`` link-local address.
    port : int
        TCP port (default 5025 — the standard SCPI raw-socket port).
    timeout : float
        Socket I/O timeout in seconds (default 30).
    read_size : int
        Maximum bytes to read per ``recv`` call (default 1 MiB).
    """

    # Valid channels for per-channel commands
    CHANNELS = (1, 2, 3, 4)

    # DAC mode look-up
    DAC_MODES = ("SINGle", "DUAL", "FOUR", "MARKer", "DCDuplicate", "DCMarker")

    SCPI_PORT = 5025

    def __init__(
        self,
        host: str,
        port: int = 5025,
        timeout: float = 30.0,
        read_size: int = 1_048_576,
    ) -> None:
        self._host = host
        self._port = port
        self._read_size = read_size
        logger.info("Connecting to %s:%d …", host, port)
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)
        logger.info("Connected.")
        # Use little-endian for binary block transfers (typical for x86 hosts)
        self.byte_order = "SWAPped"

    # ------------------------------------------------------------------
    # Low-level I/O helpers
    # ------------------------------------------------------------------

    def _send(self, data: bytes) -> None:
        """Send raw bytes, ensuring the entire buffer is transmitted."""
        self._sock.sendall(data)

    def _recv_until(self, terminator: bytes = b"\n") -> bytes:
        """Read from the socket until *terminator* is found.

        Returns the received bytes **including** the terminator.
        """
        buf = bytearray()
        while True:
            chunk = self._sock.recv(self._read_size)
            if not chunk:
                raise ConnectionError(
                    "Socket closed by remote host while reading response"
                )
            buf.extend(chunk)
            if terminator in buf:
                break
        return bytes(buf)

    def write(self, cmd: str) -> None:
        """Send a SCPI command (newline-terminated)."""
        logger.debug("SCPI TX: %s", cmd)
        self._send(cmd.encode() + b"\n")

    def query(self, cmd: str) -> str:
        """Send a SCPI query and return the stripped response string."""
        self.write(cmd)
        raw = self._recv_until(b"\n")
        resp = raw.decode().strip()
        logger.debug("SCPI RX: %s", resp)
        return resp

    def query_float(self, cmd: str) -> float:
        """Query and return a single float value."""
        return float(self.query(cmd))

    def query_int(self, cmd: str) -> int:
        """Query and return a single integer value."""
        return int(float(self.query(cmd)))

    def query_bool(self, cmd: str) -> bool:
        """Query and return a boolean (0/1)."""
        return self.query(cmd) in ("1", "ON")

    def _write_binary_block(self, header: str, data: bytes) -> None:
        """Write an IEEE 488.2 definite-length binary block.

        Constructs the ``#<n><len>`` prefix, sends header + block + newline
        as a single ``sendall`` to avoid Nagle-induced fragmentation.
        """
        length_str = str(len(data))
        prefix = f"{header} #{len(length_str)}{length_str}"
        self._send(prefix.encode() + data + b"\n")

    def close(self) -> None:
        """Close the TCP socket."""
        logger.info("Closing connection to %s:%d", self._host, self._port)
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._sock.close()

    # ------------------------------------------------------------------
    # Common / System commands
    # ------------------------------------------------------------------

    @property
    def idn(self) -> str:
        """Return the instrument identification string."""
        return self.query("*IDN?")

    def reset(self) -> None:
        """Reset the instrument to factory defaults (*RST)."""
        self.write("*RST")

    def clear_status(self) -> None:
        """Clear event registers and error queue (*CLS)."""
        self.write("*CLS")

    def opc(self) -> str:
        """Block until all pending operations complete; returns '1'."""
        return self.query("*OPC?")

    def wait(self) -> None:
        """Prevent further command execution until current ops complete."""
        self.write("*WAI")

    def self_test(self) -> int:
        """Run self-tests; returns 0 on pass, >0 = number of failures."""
        return self.query_int("*TST?")

    def self_test_detail(self) -> str:
        """Run self-tests and return detailed messages."""
        return self.query(":TEST:TST?")

    @property
    def options(self) -> str:
        """Return installed options string."""
        return self.query("*OPT?")

    @property
    def system_version(self) -> str:
        """Return SCPI version string."""
        return self.query(":SYST:VERS?")

    def get_error(self) -> str:
        """Read and clear the next error from the error queue."""
        return self.query(":SYST:ERR?")

    def check_errors(self) -> list[str]:
        """Drain the error queue and return all errors."""
        errors = []
        while True:
            err = self.get_error()
            if err.startswith("0,") or err.startswith("+0,"):
                break
            errors.append(err)
        return errors

    # ------------------------------------------------------------------
    # Instrument subsystem
    # ------------------------------------------------------------------

    @property
    def slot(self) -> int:
        """Query the AXIe slot number."""
        return self.query_int(":INST:SLOT?")

    @property
    def hw_revision(self) -> str:
        """Query the hardware revision."""
        return self.query(":INST:HWR?")

    def identify(self, seconds: int = 10) -> None:
        """Flash the front-panel Access LED for *seconds*."""
        self.write(f":INST:IDEN {seconds}")

    def identify_stop(self) -> None:
        """Stop the identification LED flashing."""
        self.write(":INST:IDEN:STOP")

    @property
    def dac_mode(self) -> str:
        """Get / set the DAC operation mode.

        Valid values: ``SINGle``, ``DUAL``, ``FOUR``,
        ``MARKer``, ``DCDuplicate``, ``DCMarker``.
        """
        return self.query(":INST:DACM?")

    @dac_mode.setter
    def dac_mode(self, mode: str) -> None:
        if mode.upper()[:4] not in [m[:4].upper() for m in self.DAC_MODES]:
            raise ValueError(
                f"Invalid DAC mode '{mode}'. " f"Choose from {self.DAC_MODES}"
            )
        self.write(f":INST:DACM {mode}")

    @property
    def memory_divider(self) -> str:
        """Get / set the extended-memory sample-rate divider (DIV1/DIV2/DIV4)."""
        return self.query(":INST:MEM:EXT:RDIV?")

    @memory_divider.setter
    def memory_divider(self, div: str) -> None:
        self.write(f":INST:MEM:EXT:RDIV {div}")

    @property
    def multi_module_config(self) -> bool:
        """Query whether multi-module configuration is enabled."""
        return self.query_bool(":INST:MMOD:CONF?")

    @property
    def multi_module_mode(self) -> str:
        """Query the multi-module mode (NORMal or SLAVe)."""
        return self.query(":INST:MMOD:MODE?")

    # ------------------------------------------------------------------
    # Byte-order (FORMat)
    # ------------------------------------------------------------------

    @property
    def byte_order(self) -> str:
        """Get / set binary transfer byte order (NORMal = big-endian,
        SWAPped = little-endian)."""
        return self.query(":FORM:BORD?")

    @byte_order.setter
    def byte_order(self, order: str) -> None:
        self.write(f":FORM:BORD {order}")

    # ------------------------------------------------------------------
    # Sampling frequency
    # ------------------------------------------------------------------

    @property
    def sample_rate(self) -> float:
        """Get / set the DAC sample rate in Hz."""
        return self.query_float(":FREQ:RAST?")

    @sample_rate.setter
    def sample_rate(self, freq: float) -> None:
        self.write(f":FREQ:RAST {freq:E}")

    # ------------------------------------------------------------------
    # Reference oscillator
    # ------------------------------------------------------------------

    @property
    def ref_clock_source(self) -> str:
        """Get / set the reference clock source (EXTernal | AXI | INTernal)."""
        return self.query(":ROSC:SOUR?")

    @ref_clock_source.setter
    def ref_clock_source(self, source: str) -> None:
        self.write(f":ROSC:SOUR {source}")

    def check_ref_clock(self, source: str) -> bool:
        """Check whether a reference clock source is available."""
        return self.query(f":ROSC:SOUR:CHEC? {source}") == "1"

    @property
    def ref_clock_frequency(self) -> float:
        """Get / set the expected external reference frequency in Hz."""
        return self.query_float(":ROSC:FREQ?")

    @ref_clock_frequency.setter
    def ref_clock_frequency(self, freq: float) -> None:
        self.write(f":ROSC:FREQ {freq:E}")

    @property
    def ref_clock_range(self) -> str:
        """Get / set the reference clock range (RANG1: 10–300 MHz,
        RANG2: 210 MHz–17 GHz)."""
        return self.query(":ROSC:RANG?")

    @ref_clock_range.setter
    def ref_clock_range(self, rng: str) -> None:
        self.write(f":ROSC:RANG {rng}")

    # ------------------------------------------------------------------
    # Output subsystem
    # ------------------------------------------------------------------

    def _ch(self, channel: int) -> int:
        if channel not in self.CHANNELS:
            raise ValueError(f"Channel must be one of {self.CHANNELS}")
        return channel

    def set_output(self, channel: int, state: bool) -> None:
        """Enable or disable the output amplifier on *channel*."""
        self.write(f":OUTP{self._ch(channel)} {'ON' if state else 'OFF'}")

    def get_output(self, channel: int) -> bool:
        """Query the output state of *channel*."""
        return self.query_bool(f":OUTP{self._ch(channel)}?")

    @property
    def ref_clock_output_source(self) -> str:
        """Get / set the reference clock output source
        (INTernal | EXTernal | SCLK1 | SCLK2)."""
        return self.query(":OUTP:ROSC:SOUR?")

    @ref_clock_output_source.setter
    def ref_clock_output_source(self, source: str) -> None:
        self.write(f":OUTP:ROSC:SOUR {source}")

    def set_ref_clock_divider(self, scd: int) -> None:
        """Set the sample-clock divider for the REF CLK OUT."""
        self.write(f":OUTP:ROSC:SCD {scd}")

    def get_ref_clock_divider(self) -> int:
        return self.query_int(":OUTP:ROSC:SCD?")

    def set_differential_offset(self, channel: int, value: float) -> None:
        """Set the differential offset for *channel*."""
        self.write(f":OUTP{self._ch(channel)}:DIOF {value}")

    def get_differential_offset(self, channel: int) -> float:
        return self.query_float(f":OUTP{self._ch(channel)}:DIOF?")

    # ------------------------------------------------------------------
    # Voltage subsystem
    # ------------------------------------------------------------------

    def set_amplitude(self, channel: int, volts: float) -> None:
        """Set the peak-to-peak output amplitude on *channel* (V)."""
        self.write(f":VOLT{self._ch(channel)} {volts}")

    def get_amplitude(self, channel: int) -> float:
        return self.query_float(f":VOLT{self._ch(channel)}?")

    def set_offset(self, channel: int, volts: float) -> None:
        """Set the output DC offset on *channel* (V)."""
        self.write(f":VOLT{self._ch(channel)}:OFFS {volts}")

    def get_offset(self, channel: int) -> float:
        return self.query_float(f":VOLT{self._ch(channel)}:OFFS?")

    def set_high_level(self, channel: int, volts: float) -> None:
        """Set the output high level on *channel* (V)."""
        self.write(f":VOLT{self._ch(channel)}:HIGH {volts}")

    def get_high_level(self, channel: int) -> float:
        return self.query_float(f":VOLT{self._ch(channel)}:HIGH?")

    def set_low_level(self, channel: int, volts: float) -> None:
        """Set the output low level on *channel* (V)."""
        self.write(f":VOLT{self._ch(channel)}:LOW {volts}")

    def get_low_level(self, channel: int) -> float:
        return self.query_float(f":VOLT{self._ch(channel)}:LOW?")

    def set_termination_voltage(self, channel: int, volts: float) -> None:
        """Set the external termination voltage on *channel* (V)."""
        self.write(f":VOLT{self._ch(channel)}:TERM {volts}")

    def get_termination_voltage(self, channel: int) -> float:
        return self.query_float(f":VOLT{self._ch(channel)}:TERM?")

    # ------------------------------------------------------------------
    # FIR filter subsystem
    # ------------------------------------------------------------------

    def set_fir_filter_type(
        self,
        channel: int,
        rate: str,
        filter_type: str,
    ) -> None:
        """Set the predefined FIR filter type for *channel*.

        Parameters
        ----------
        rate : str
            ``"FRAT"`` (divider 1), ``"HRAT"`` (divider 2), or
            ``"QRAT"`` (divider 4).
        filter_type : str
            Depends on *rate*:
            FRAT → LOWPass | ZOH | USER;
            HRAT/QRAT → NYQuist | LINear | ZOH | USER.
        """
        self.write(f":OUTP{self._ch(channel)}:FILT:{rate}:TYPE {filter_type}")

    def get_fir_filter_type(self, channel: int, rate: str) -> str:
        return self.query(f":OUTP{self._ch(channel)}:FILT:{rate}:TYPE?")

    def set_fir_filter_scale(self, channel: int, rate: str, scale: float) -> None:
        """Set FIR filter scaling factor (0–1)."""
        self.write(f":OUTP{self._ch(channel)}:FILT:{rate}:SCAL {scale}")

    def set_fir_filter_delay(self, channel: int, rate: str, delay: float) -> None:
        """Set FIR filter delay in seconds."""
        self.write(f":OUTP{self._ch(channel)}:FILT:{rate}:DEL {delay}")

    # ------------------------------------------------------------------
    # Function mode
    # ------------------------------------------------------------------

    @property
    def function_mode(self) -> str:
        """Get / set waveform generation mode
        (ARBitrary | STSequence | STSCenario)."""
        return self.query(":FUNC:MODE?")

    @function_mode.setter
    def function_mode(self, mode: str) -> None:
        self.write(f":FUNC:MODE {mode}")

    # ------------------------------------------------------------------
    # Trace (waveform memory) subsystem
    # ------------------------------------------------------------------

    def set_memory_mode(self, channel: int, mode: str) -> None:
        """Set the waveform sample source for *channel*
        (INTernal | EXTended)."""
        self.write(f":TRAC{self._ch(channel)}:MMOD {mode}")

    def get_memory_mode(self, channel: int) -> str:
        return self.query(f":TRAC{self._ch(channel)}:MMOD?")

    def define_segment(
        self,
        channel: int,
        segment_id: int,
        length: int,
        init_value: Optional[int] = None,
        write_only: bool = False,
    ) -> None:
        """Define a waveform segment in memory.

        Parameters
        ----------
        channel : int
            Target channel (1–4).
        segment_id : int
            Segment identifier.
        length : int
            Segment length in samples.
        init_value : int, optional
            If given, initialise all samples to this signed 8-bit DAC value.
        write_only : bool
            If True, segment cannot be read back.
        """
        ch = self._ch(channel)
        cmd = "WONL" if write_only else "DEF"
        parts = f":TRAC{ch}:DEF{':WONL' if write_only else ''} {segment_id},{length}"
        if init_value is not None:
            parts += f",{init_value}"
        self.write(parts)

    def define_segment_new(
        self,
        channel: int,
        length: int,
        init_value: Optional[int] = None,
        write_only: bool = False,
    ) -> int:
        """Define a segment and let the instrument assign the ID.

        Returns the auto-assigned segment_id.
        """
        ch = self._ch(channel)
        wonl = ":WONL" if write_only else ""
        cmd = f":TRAC{ch}:DEF{wonl}:NEW? {length}"
        if init_value is not None:
            cmd += f",{init_value}"
        return self.query_int(cmd)

    def load_waveform(
        self,
        channel: int,
        segment_id: int,
        data: np.ndarray,
        offset: int = 0,
    ) -> None:
        """Download waveform data into a segment using binary block transfer.

        Parameters
        ----------
        channel : int
            Target channel (1–4).
        segment_id : int
            Pre-defined segment ID.
        data : np.ndarray
            Signed 8-bit sample array (dtype ``int8``, range −128…+127).
            In MARKer / DCMarker modes, interleave waveform and marker bytes.
        offset : int
            Sample offset within the segment (default 0).
        """
        ch = self._ch(channel)
        samples = np.asarray(data, dtype=np.int8)
        raw = samples.tobytes()
        self._write_binary_block(f":TRAC{ch}:DATA {segment_id},{offset},", raw)

    def load_waveform_float(
        self,
        channel: int,
        segment_id: int,
        data: np.ndarray,
        offset: int = 0,
    ) -> None:
        """Download waveform data from a float array (−1.0 … +1.0),
        auto-scaling to int8.

        Parameters
        ----------
        data : np.ndarray
            Float array in the range [−1.0, +1.0].
        """
        scaled = np.clip(data, -1.0, 1.0) * 127
        int_data = np.round(scaled).astype(np.int8)
        self.load_waveform(channel, segment_id, int_data, offset)

    def read_waveform(
        self,
        channel: int,
        segment_id: int,
        offset: int,
        length: int,
    ) -> np.ndarray:
        """Read waveform data back from a segment.

        Returns an int8 numpy array.
        """
        ch = self._ch(channel)
        raw = self.query(f":TRAC{ch}:DATA? {segment_id},{offset},{length}")
        values = [int(v) for v in raw.split(",")]
        return np.array(values, dtype=np.int8)

    def delete_segment(self, channel: int, segment_id: int) -> None:
        """Delete a single segment from waveform memory."""
        self.write(f":TRAC{self._ch(channel)}:DEL {segment_id}")

    def delete_all_segments(self, channel: int) -> None:
        """Delete all segments from waveform memory on *channel*."""
        self.write(f":TRAC{self._ch(channel)}:DEL:ALL")

    def catalog(self, channel: int) -> list[tuple[int, int]]:
        """Return a list of (segment_id, length) tuples for *channel*."""
        raw = self.query(f":TRAC{self._ch(channel)}:CAT?")
        vals = [int(v) for v in raw.split(",")]
        if vals == [0, 0]:
            return []
        return list(zip(vals[0::2], vals[1::2]))

    def free_memory(self, channel: int) -> tuple[int, int, int]:
        """Return (bytes_available, bytes_in_use, contiguous_bytes)."""
        raw = self.query(f":TRAC{self._ch(channel)}:FREE?")
        parts = [int(v) for v in raw.split(",")]
        return tuple(parts)  # type: ignore[return-value]

    def select_segment(self, channel: int, segment_id: int) -> None:
        """Select the active segment for arbitrary mode playback."""
        self.write(f":TRAC{self._ch(channel)}:SEL {segment_id}")

    def get_selected_segment(self, channel: int) -> int:
        return self.query_int(f":TRAC{self._ch(channel)}:SEL?")

    def set_segment_advance_mode(self, channel: int, mode: str) -> None:
        """Set segment advancement mode (AUTO | COND | REP | SING)."""
        self.write(f":TRAC{self._ch(channel)}:ADV {mode}")

    def set_segment_loop_count(self, channel: int, count: int) -> None:
        """Set the segment loop count (1 … 4G−1)."""
        self.write(f":TRAC{self._ch(channel)}:COUN {count}")

    def set_segment_marker(self, channel: int, state: bool) -> None:
        """Enable or disable markers for the selected segment."""
        self.write(f":TRAC{self._ch(channel)}:MARK {'ON' if state else 'OFF'}")

    def set_segment_name(self, channel: int, segment_id: int, name: str) -> None:
        """Associate a name (≤32 chars) with a segment."""
        self.write(f':TRAC{self._ch(channel)}:NAME {segment_id},"{name}"')

    def set_segment_comment(self, channel: int, segment_id: int, comment: str) -> None:
        """Associate a comment (≤256 chars) with a segment."""
        self.write(f':TRAC{self._ch(channel)}:COMM {segment_id},"{comment}"')

    def import_waveform(
        self,
        channel: int,
        segment_id: int,
        filepath: str,
        file_format: str = "BIN8",
        data_type: str = "IONLY",
        marker_flag: Optional[str] = None,
        padding: str = "ALEN",
    ) -> None:
        """Import waveform data from a file on the instrument's filesystem.

        Parameters
        ----------
        file_format : str
            TXT | BIN | BIN8 | IQBIN | BIN6030 | BIN5110 | LICensed |
            MAT89600 | DSA90000 | CSV
        data_type : str
            IONLY | QONLY | BOTH
        marker_flag : str, optional
            ON | OFF  (applicable to BIN5110 only)
        padding : str
            ALEN | FILL
        """
        ch = self._ch(channel)
        cmd = f':TRAC{ch}:IMP {segment_id},"{filepath}",{file_format},{data_type}'
        if marker_flag is not None:
            cmd += f",{marker_flag}"
        cmd += f",{padding}"
        self.write(cmd)

    # ------------------------------------------------------------------
    # Sequence table subsystem
    # ------------------------------------------------------------------

    def sequence_table_reset(self) -> None:
        """Reset all sequence table entries to defaults."""
        self.write(":STAB:RES")

    def sequence_table_write(
        self,
        index: int,
        control: int,
        seq_loop: int,
        seg_loop: int,
        segment_id: int,
        start_offset: int = 0,
        end_offset: int = 0xFFFFFFFF,
    ) -> None:
        """Write a *data* entry into the sequence table.

        Parameters
        ----------
        index : int
            Sequence table index.
        control : int
            Control word (e.g. 0x10000000 for Init-Sequence marker).
        seq_loop : int
            Sequence loop count (1 … 4G−1).
        seg_loop : int
            Segment loop count (1 … 4G−1).
        segment_id : int
            Target segment ID.
        start_offset : int
            Segment start offset in samples.
        end_offset : int
            Segment end offset (0xFFFFFFFF = end of segment).
        """
        self.write(
            f":STAB:DATA {index},{control},{seq_loop},"
            f"{seg_loop},{segment_id},{start_offset},{end_offset}"
        )

    def sequence_table_write_idle(
        self,
        index: int,
        control: int,
        seq_loop: int,
        idle_sample: int = 0,
        idle_delay: int = 2560,
    ) -> None:
        """Write an *idle delay* entry into the sequence table.

        Parameters
        ----------
        control : int
            Must include command flag 0x80000000.
        idle_sample : int
            8-bit DAC sample value played during pause.
        idle_delay : int
            Idle delay in waveform sample clocks.
        """
        self.write(
            f":STAB:DATA {index},{control},{seq_loop},"
            f"0,{idle_sample},{idle_delay},0"
        )

    def sequence_select(self, index: int) -> None:
        """Select the starting sequence-table index in STSequence mode."""
        self.write(f":STAB:SEQ:SEL {index}")

    @property
    def sequence_state(self) -> int:
        """Query the current sequence execution state (encoded int)."""
        return self.query_int(":STAB:SEQ:STAT?")

    @property
    def dynamic_mode(self) -> bool:
        """Get / set dynamic sequencing mode."""
        return self.query_bool(":STAB:DYN?")

    @dynamic_mode.setter
    def dynamic_mode(self, state: bool) -> None:
        self.write(f":STAB:DYN {'ON' if state else 'OFF'}")

    def dynamic_select(self, index: int) -> None:
        """In dynamic mode, select the next sequence-table entry."""
        self.write(f":STAB:DYN:SEL {index}")

    def scenario_select(self, index: int) -> None:
        """Select the starting sequence-table index in STSCenario mode."""
        self.write(f":STAB:SCEN:SEL {index}")

    def set_scenario_advance_mode(self, mode: str) -> None:
        """Set scenario advancement mode (AUTO | COND | REP | SING)."""
        self.write(f":STAB:SCEN:ADV {mode}")

    def set_scenario_loop_count(self, count: int) -> None:
        """Set the scenario loop count."""
        self.write(f":STAB:SCEN:COUN {count}")

    # ------------------------------------------------------------------
    # Carrier (DUC) subsystem
    # ------------------------------------------------------------------

    def set_carrier_frequency(self, channel: int, freq: float) -> None:
        """Set the carrier frequency for digital up-conversion (Hz)."""
        self.write(f":CARR{self._ch(channel)}:FREQ {freq:E}")

    def get_carrier_frequency(self, channel: int) -> float:
        return self.query_float(f":CARR{self._ch(channel)}:FREQ?")

    def set_carrier_scale(self, channel: int, scale: float) -> None:
        """Set the carrier amplitude scale factor."""
        self.write(f":CARR{self._ch(channel)}:SCAL {scale}")

    def get_carrier_scale(self, channel: int) -> float:
        return self.query_float(f":CARR{self._ch(channel)}:SCAL?")

    # ------------------------------------------------------------------
    # ARM / Trigger subsystem
    # ------------------------------------------------------------------

    def abort(self, channel: Optional[int] = None) -> None:
        """Stop signal generation on *channel* (or all channels)."""
        suffix = str(channel) if channel else ""
        self.write(f":ABOR{suffix}")

    def start(self, channel: Optional[int] = None) -> None:
        """Start (initiate) signal generation on *channel* (or all)."""
        suffix = str(channel) if channel else ""
        self.write(f":INIT:IMM{suffix}")

    @property
    def arm_mode(self) -> str:
        """Get / set the arm mode (SELF | ARMed)."""
        return self.query(":INIT:CONT:ENAB?")

    @arm_mode.setter
    def arm_mode(self, mode: str) -> None:
        self.write(f":INIT:CONT:ENAB {mode}")

    @property
    def continuous(self) -> bool:
        """Get / set the continuous (trigger-mode) state."""
        return self.query_bool(":INIT:CONT?")

    @continuous.setter
    def continuous(self, state: bool) -> None:
        self.write(f":INIT:CONT {'ON' if state else 'OFF'}")

    @property
    def gate_mode(self) -> bool:
        """Get / set the gate trigger mode."""
        return self.query_bool(":INIT:GATE?")

    @gate_mode.setter
    def gate_mode(self, state: bool) -> None:
        self.write(f":INIT:GATE {'ON' if state else 'OFF'}")

    # -- Trigger input configuration --

    @property
    def trigger_source(self) -> str:
        """Get / set the trigger source (TRIGger | EVENt | INTernal)."""
        return self.query(":ARM:TRIG:SOUR?")

    @trigger_source.setter
    def trigger_source(self, source: str) -> None:
        self.write(f":ARM:TRIG:SOUR {source}")

    @property
    def trigger_level(self) -> float:
        """Get / set the trigger input threshold level (V)."""
        return self.query_float(":ARM:TRIG:LEV?")

    @trigger_level.setter
    def trigger_level(self, level: float) -> None:
        self.write(f":ARM:TRIG:LEV {level}")

    @property
    def trigger_slope(self) -> str:
        """Get / set the trigger input slope (POSitive | NEGative | EITHer)."""
        return self.query(":ARM:TRIG:SLOP?")

    @trigger_slope.setter
    def trigger_slope(self, slope: str) -> None:
        self.write(f":ARM:TRIG:SLOP {slope}")

    @property
    def trigger_frequency(self) -> float:
        """Get / set the internal trigger generator frequency (Hz)."""
        return self.query_float(":ARM:TRIG:FREQ?")

    @trigger_frequency.setter
    def trigger_frequency(self, freq: float) -> None:
        self.write(f":ARM:TRIG:FREQ {freq}")

    @property
    def trigger_operation(self) -> str:
        """Get / set trigger operation mode (ASYNchronous | SYNChronous)."""
        return self.query(":ARM:TRIG:OPER?")

    @trigger_operation.setter
    def trigger_operation(self, mode: str) -> None:
        self.write(f":ARM:TRIG:OPER {mode}")

    def set_module_delay(self, delay: float) -> None:
        """Set the module delay for multi-module sync (seconds)."""
        self.write(f":ARM:MDEL {delay}")

    def get_module_delay(self) -> float:
        return self.query_float(":ARM:MDEL?")

    def set_sample_delay(self, channel: int, delay: float) -> None:
        """Set per-channel sample delay (seconds)."""
        self.write(f":ARM:SDEL{self._ch(channel)} {delay}")

    def get_sample_delay(self, channel: int) -> float:
        return self.query_float(f":ARM:SDEL{self._ch(channel)}?")

    # -- Event input --

    @property
    def event_level(self) -> float:
        """Get / set the event input threshold level (V)."""
        return self.query_float(":ARM:EVEN:LEV?")

    @event_level.setter
    def event_level(self, level: float) -> None:
        self.write(f":ARM:EVEN:LEV {level}")

    @property
    def event_slope(self) -> str:
        """Get / set the event input slope (POSitive | NEGative | EITHer)."""
        return self.query(":ARM:EVEN:SLOP?")

    @event_slope.setter
    def event_slope(self, slope: str) -> None:
        self.write(f":ARM:EVEN:SLOP {slope}")

    # -- Software trigger / enable / advance --

    def force_trigger(self) -> None:
        """Send a software trigger (begin) event."""
        self.write(":TRIG:BEG")

    def force_enable(self) -> None:
        """Send a software enable event."""
        self.write(":TRIG:ENAB")

    def force_advance(self) -> None:
        """Send a software advancement event."""
        self.write(":TRIG:ADV")

    def set_gate(self, state: bool) -> None:
        """In gated mode, open or close the gate."""
        self.write(f":TRIG:BEG:GATE {'ON' if state else 'OFF'}")

    # -- HW disable for trigger functions --

    def set_trigger_hw_disable(self, function: str, state: bool) -> None:
        """Disable the hardware input for a trigger function.

        Parameters
        ----------
        function : str
            ``"ENAB"`` (enable), ``"BEG"`` (trigger), or ``"ADV"`` (advance).
        state : bool
            True to disable hardware input (software-only triggering).
        """
        self.write(f":TRIG:{function}:HWD {'ON' if state else 'OFF'}")

    def set_advance_source(self, source: str) -> None:
        """Set the advancement event source (TRIGger | EVENt | INTernal)."""
        self.write(f":TRIG:SOUR:ADV {source}")

    def set_enable_source(self, source: str) -> None:
        """Set the enable event source (TRIGger | EVENt)."""
        self.write(f":TRIG:SOUR:ENAB {source}")

    # ------------------------------------------------------------------
    # Mass-memory subsystem
    # ------------------------------------------------------------------

    def mmemory_catalog(self, directory: str = "") -> str:
        """List files in *directory* on the instrument."""
        if directory:
            return self.query(f':MMEM:CAT? "{directory}"')
        return self.query(":MMEM:CAT?")

    def mmemory_cd(self, directory: str) -> None:
        """Change the current directory on the instrument."""
        self.write(f':MMEM:CDIR "{directory}"')

    def mmemory_save_state(self, filepath: str) -> None:
        """Save the current instrument state to a file."""
        self.write(f':MMEM:STOR:CST "{filepath}"')

    def mmemory_load_state(self, filepath: str) -> None:
        """Load instrument state from a file."""
        self.write(f':MMEM:LOAD:CST "{filepath}"')

    def mmemory_delete(self, filepath: str) -> None:
        """Delete a file on the instrument."""
        self.write(f':MMEM:DEL "{filepath}"')

    def mmemory_mkdir(self, directory: str) -> None:
        """Create a directory on the instrument."""
        self.write(f':MMEM:MDIR "{directory}"')

    # ------------------------------------------------------------------
    # Status subsystem
    # ------------------------------------------------------------------

    def status_preset(self) -> None:
        """Preset all status register enable/transition filters."""
        self.write(":STAT:PRES")

    @property
    def status_byte(self) -> int:
        """Read the status byte register."""
        return self.query_int("*STB?")

    @property
    def questionable_event(self) -> int:
        """Read the questionable data event register."""
        return self.query_int(":STAT:QUES:EVEN?")

    @property
    def operation_event(self) -> int:
        """Read the operation event register."""
        return self.query_int(":STAT:OPER:EVEN?")

    def __repr__(self) -> str:
        try:
            return f"M8195A({self._host}:{self._port}, {self.idn!r})"
        except Exception:
            return f"M8195A({self._host}:{self._port}, <not responding>)"

    # Context-manager support
    def __enter__(self) -> "M8195A":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
