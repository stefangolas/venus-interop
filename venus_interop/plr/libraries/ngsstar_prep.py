"""Hamilton's NGSStar framework, `NGSStarPrep` (`NGSStar\\<kit>\\Library\\NGSStarPrep.hsi`): the
devices a kit method drives besides the STAR, on PLR's drivers. Hamilton heater shakers (HHS), the
Inheco CPAC (a TEC on an Inheco control box) and the Inheco ODTC thermocycler.

Each function is the driver calls the library makes; what it adds on top of them is kept:
- HHS_Init closes and opens the plate lock of every HHS the method names; HHS_Shake starts the
  shaker, waits the duration and stops it, the plate left locked; HHS_SetTemperature turns
  temperature control off, then on at the new temperature unless that is 0.
- ODTC_DownloadProtocol stores a MethodSet XML (the kit's `Files\\ODTC_scripts`) on the ODTC;
  ODTC_ExecuteProtocol starts one of its methods by name and returns at once (priority 10000 to cut
  a PreMethod's pre-heating short, else 10), and ODTC_WaitForStartedProtocolToFinish waits for it:
  the method pipettes in between. Venus also returns the device's estimate of the run time, which
  PLR's driver doesn't report: the duration returned is None, and the wait then has no time limit
  (Venus allows the estimate plus 20 s).
Venus's simulation mode (DATA_HandOverSimulationModeForAllLocalSMTs) leaves the devices alone and
doesn't wait, as the library does for the HHS and CPAC (Venus's ODTC driver simulates itself).

Not ported: connecting the devices (CreateUsbDevice / CreateStarDevice, TEC Initialize, ODTC
Connect / Reset / Initialize: `setup()` the PLR devices first, as the STAR), serial numbers,
firmware versions, trace levels, the status-window texts, the error dialogs (a PLR driver error
ends the run, as Cancel does in Venus), the UV-kit question and the waste sensor check (operator
dialogs; PLR has no driver for Hamilton's waste sensor). PLR's temperature controllers refuse to
cool a device that only heats (the HHS) where Venus just sets the target; Avenio only heats.
"""
from __future__ import annotations

import asyncio
import pathlib
from typing import Callable, Optional

LIBRARY = "NGSSTARPREP"  # the Venus namespace ported


class NGSStarPrep:
  def __init__(self, heater_shakers: Optional[dict] = None, cpac=None, odtcs: Optional[dict] = None,
               simulation: bool = False, time_scale: float = 1.0, sleep=None,
               read_file: Optional[Callable[[str], str]] = None):
    """`heater_shakers`: the Venus node number (1-5; the TCC number for one on the STAR) -> a PLR
    HeaterShaker. `cpac`: the CPAC (an InhecoTemperatureController). `odtcs`: the ODTC's address
    (what the method passes to ODTC_Init) -> a PLR InhecoODTC or its ExperimentalODTCBackend.
    `time_scale` scales the shaking waits (1: real time). `read_file` reads a MethodSet file."""
    self.heater_shakers, self.cpac, self.odtcs = heater_shakers or {}, cpac, odtcs or {}
    self.simulation = simulation
    self.time_scale, self.sleep = time_scale, sleep or asyncio.sleep
    self.read_file = read_file or (lambda path: pathlib.Path(path).read_text(encoding="utf-8"))
    self._odtc: dict[int, object] = {}  # Venus device number -> the ODTC's backend
    self._runs: dict[int, asyncio.Task] = {}  # request id -> the running method
    self._requests = 0
    self._hhs_used: list[int] = []

  def DATA_HandOverSimulationModeForAllLocalSMTs(self, simulation_on, show_uv_dialog=0) -> None:
    """Venus's simulation mode for the devices. The UV-kit question (a dialog that ends the method
    to run the UV decontamination instead) is not ported."""
    self.simulation = bool(simulation_on)

  def LiquidWasteSensor_Init(self, com_port) -> None:
    """The liquid and solid waste sensor check: operator dialogs, not ported."""

  # -- Hamilton heater shakers ---------------------------------------------------------------

  def _hhs(self, handle):
    if int(handle) not in self.heater_shakers:
      raise KeyError(f"HHS {handle}: no heater shaker given for it")
    return self.heater_shakers[int(handle)]

  async def HHS_Init(self, kind1="0", kind2="0", kind3="0", kind4="0", kind5="0", ML_STAR=None) -> tuple:
    """The handles of HHS 1-5 ("TCC": on the STAR, "HHSB": on the heater shaker box, "0": none;
    only 1 and 2 can be "TCC"), 0 for none; each named one has its plate lock closed and opened."""
    kinds = (kind1, kind2, kind3, kind4, kind5)
    handles = tuple(n if k in ("TCC", "HHSB") and (k == "HHSB" or n <= 2) else 0 for n, k in enumerate(kinds, 1))
    self._hhs_used = [h for h in handles if h]
    if not self.simulation:
      for n, kind in enumerate(kinds, 1):
        if kind != "0":
          hs = self._hhs(n)
          await hs.lock_plate()
          await hs.unlock_plate()
    return handles

  async def HHS_SetTemperature(self, hhs, temperature: float) -> None:
    if self.simulation:
      return
    hs = self._hhs(hhs)
    await hs.deactivate()
    if temperature != 0:
      await hs.set_temperature(float(temperature))

  async def HHS_Shake(self, hhs, speed: int, seconds: float) -> None:
    """Shake at `speed` rpm for `seconds`; the plate stays locked."""
    if self.simulation:
      return
    hs = self._hhs(hhs)
    await hs.shake(speed=speed)  # locks the plate and starts, without waiting
    await self.sleep(seconds * self.time_scale)
    await hs.stop_shaking()

  async def HHS_Terminate(self, hhs1=0, hhs2=0, hhs3=0, hhs4=0, hhs5=0) -> None:
    """Every shaker stopped (StopAllShaker), then the temperature control of each handle given."""
    if self.simulation:
      return
    for h in self._hhs_used:
      await self._hhs(h).stop_shaking()
    for h in (hhs1, hhs2, hhs3, hhs4, hhs5):
      if h:
        await self._hhs(h).deactivate()

  # -- Inheco CPAC ---------------------------------------------------------------------------

  def CPAC_Init(self) -> None:
    """Connecting the control box (`setup()` the CPAC's control box first)."""

  async def CPAC_SetTemperature(self, temperature: float) -> None:
    if not self.simulation:
      await self.cpac.set_temperature(float(temperature))

  async def CPAC_Terminate(self) -> None:
    if not self.simulation:
      await self.cpac.stop_temperature_control()

  # -- Inheco ODTC ---------------------------------------------------------------------------

  def _backend(self, device):
    odtc = self._odtc[int(device)]
    return getattr(odtc, "backend", odtc)

  def ODTC_Init(self, address: str, local_ip_address: str = "") -> int:
    """The ODTC at `address` (set up already), as the next device number."""
    number = len(self._odtc) + 1
    self._odtc[number] = self.odtcs[address] if not self.simulation else self.odtcs.get(address)
    return number

  async def ODTC_DownloadProtocol(self, device, method_set_file: str) -> None:
    if not self.simulation:
      await self._backend(device).upload_method_set(self.read_file(method_set_file))

  async def ODTC_ExecuteProtocol(self, device, method_set_file: str, method_name: str,
                                 shorten_preheating=0) -> tuple[Optional[int], int]:
    """Start `method_name` (stored on the ODTC) and return (its duration: None, the request id).
    `method_set_file` is only shown in Venus's status window."""
    self._requests += 1
    request = self._requests
    if not self.simulation:
      run = self._backend(device).execute_method(method_name, priority=10000 if shorten_preheating else 10)
      self._runs[request] = asyncio.ensure_future(run)
      await asyncio.sleep(0)  # the command goes out before this returns, as in Venus
    return None, request

  async def ODTC_WaitForStartedProtocolToFinish(self, device, timeout: Optional[float], request: int) -> None:
    run = self._runs.pop(int(request), None)
    if run is not None:
      await asyncio.wait_for(run, None if timeout is None else (timeout + 20) * self.time_scale or None)

  async def ODTC_OpenDoor(self, device) -> None:
    if not self.simulation:
      await self._backend(device).open_lid()

  async def ODTC_CloseDoor(self, device) -> None:
    if not self.simulation:
      await self._backend(device).close_lid()

  async def ODTC_Terminate(self, device, open_door=0) -> None:
    """The running method stopped, the door opened if asked."""
    if self.simulation:
      return
    backend = self._backend(device)
    await backend.stop_method()
    if open_door:
      await backend.open_lid()
