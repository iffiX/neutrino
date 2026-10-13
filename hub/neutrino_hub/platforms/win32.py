"""The hub's one Win32 binding: the libraries, their prototypes, the names.

Copied from the agent's and cut to what the hub calls: the service
dispatcher, the job its children run in, the elevation check, starting
``nhub`` elevated through the UAC prompt, and iphlpapi's network tables.
Nothing binds a library at import time, so this module imports on Linux as
readily as on Windows and the seams above it stay replaceable in tests.
"""

import ctypes

# A DWORD is 32 bits on Windows; c_ulong is 64 on Linux, where the tests
# build these same structures.
DWORD = ctypes.c_uint32

# Services: the one kind the hub is, the states it reports, the controls it
# accepts and answers.
SERVICE_WIN32_OWN_PROCESS = 0x00000010
SERVICE_STOPPED = 1
SERVICE_START_PENDING = 2
SERVICE_STOP_PENDING = 3
SERVICE_RUNNING = 4
SERVICE_ACCEPT_STOP = 0x00000001
SERVICE_ACCEPT_SHUTDOWN = 0x00000004
SERVICE_CONTROL_STOP = 0x00000001
SERVICE_CONTROL_INTERROGATE = 0x00000004
SERVICE_CONTROL_SHUTDOWN = 0x00000005
NO_ERROR = 0
ERROR_CALL_NOT_IMPLEMENTED = 120

# Job objects: every child of the service dies with the job's last handle.
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9

# Starting a program elevated: the verb that asks UAC, the window it gets,
# and waiting for it.
SHELL_VERB_RUNAS = "runas"
SW_HIDE = 0
SEE_MASK_NOCLOSEPROCESS = 0x00000040
INFINITE = 0xFFFFFFFF

# iphlpapi: the address families as Windows numbers them, the answer that asks
# for a larger buffer, and what GetAdaptersAddresses leaves out.
AF_UNSPEC = 0
AF_INET = 2
AF_INET6 = 23
ERROR_BUFFER_OVERFLOW = 111
GAA_FLAG_SKIP_ANYCAST = 0x0002
GAA_FLAG_SKIP_MULTICAST = 0x0004
IF_TYPE_SOFTWARE_LOOPBACK = 24
IF_TYPE_TUNNEL = 131
IF_OPER_STATUS_UP = 1
# An interface alias is at most this many characters, before its terminator.
IF_MAX_STRING_SIZE = 256
# A MIB table is its row count, then its rows from this byte.
MIB_TABLE_ROWS_OFFSET = 8
# The words Get-NetIPAddress prints for NL_DAD_STATE and NL_SUFFIX_ORIGIN.
NL_DAD_STATE_WORDS = {
    0: "Invalid",
    1: "Tentative",
    2: "Duplicate",
    3: "Deprecated",
    4: "Preferred",
}
NL_SUFFIX_ORIGIN_WORDS = {
    0: "Other",
    1: "Manual",
    2: "WellKnown",
    3: "Dhcp",
    4: "Link",
    5: "Random",
}

# IP_ADAPTER_ADDRESSES_LH on x64, read by byte offset: its members point
# into the same buffer.
ADAPTER_IF_INDEX_OFFSET = 4  # IfIndex, DWORD
ADAPTER_NEXT_OFFSET = 8  # Next, pointer
ADAPTER_FIRST_UNICAST_OFFSET = 24  # FirstUnicastAddress, pointer
ADAPTER_FIRST_DNS_SERVER_OFFSET = 48  # FirstDnsServerAddress, pointer
ADAPTER_FRIENDLY_NAME_OFFSET = 72  # FriendlyName, pointer to UTF-16
ADAPTER_PHYSICAL_ADDRESS_OFFSET = 80  # PhysicalAddress, 8 bytes
ADAPTER_PHYSICAL_ADDRESS_LENGTH_OFFSET = 88  # PhysicalAddressLength, DWORD
ADAPTER_IF_TYPE_OFFSET = 100  # IfType, DWORD
ADAPTER_OPER_STATUS_OFFSET = 104  # OperStatus, enum
ADAPTER_IPV4_METRIC_OFFSET = 216  # Ipv4Metric, DWORD
ADAPTER_LUID_OFFSET = 224  # Luid, 64 bits
# IP_ADAPTER_UNICAST_ADDRESS_LH and IP_ADAPTER_DNS_SERVER_ADDRESS_XP: Next,
# then Address.lpSockaddr; the unicast entry's OnLinkPrefixLength further on.
ADDRESS_NEXT_OFFSET = 8  # Next, pointer
ADDRESS_SOCKADDR_OFFSET = 16  # Address.lpSockaddr, pointer
ADDRESS_ON_LINK_PREFIX_LENGTH_OFFSET = 56  # OnLinkPrefixLength, UINT8

_LIBRARIES = None


def last_error() -> OSError:
    """The calling thread's last Win32 error, as the OSError it is.

    Returns:
        The error; off Windows, a plain OSError naming the number.
    """
    code = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else 0
    return returned_error(code)


def returned_error(code: int) -> OSError:
    """A Win32 error code a call returned, as the OSError it is.

    Args:
        code: The code.

    Returns:
        The error; off Windows, a plain OSError naming the number.
    """
    maker = getattr(ctypes, "WinError", None)
    if maker is None:
        return OSError(code, f"error {code}")
    return maker(code)


def service_main_type():
    """The LPSERVICE_MAIN_FUNCTIONW signature a service's main is wrapped in.

    Returns:
        The ctypes function type: stdcall, taking the argument count and
        the argument vector.

    Raises:
        AttributeError: Off Windows, where ctypes has no stdcall convention.
    """
    return ctypes.WINFUNCTYPE(None, DWORD, ctypes.c_void_p)


def service_handler_type():
    """The LPHANDLER_FUNCTION_EX signature a control handler is wrapped in.

    Returns:
        The ctypes function type: stdcall, taking the control, the event
        type, the event data and the context, answering a DWORD.

    Raises:
        AttributeError: Off Windows, where ctypes has no stdcall convention.
    """
    return ctypes.WINFUNCTYPE(DWORD, DWORD, DWORD, ctypes.c_void_p, ctypes.c_void_p)


def libraries() -> "Win32Libraries":
    """The bound libraries, built on first use.

    Returns:
        The one :class:`Win32Libraries` this process shares.

    Raises:
        OSError: When a library cannot be loaded, which is every call off
            Windows.
    """
    global _LIBRARIES
    if _LIBRARIES is None:
        _LIBRARIES = Win32Libraries()
    return _LIBRARIES


class ServiceStatus(ctypes.Structure):
    """What a service reports to the service control manager."""

    _fields_ = [
        ("dwServiceType", DWORD),
        ("dwCurrentState", DWORD),
        ("dwControlsAccepted", DWORD),
        ("dwWin32ExitCode", DWORD),
        ("dwServiceSpecificExitCode", DWORD),
        ("dwCheckPoint", DWORD),
        ("dwWaitHint", DWORD),
    ]


class ServiceTableEntry(ctypes.Structure):
    """One row of the table StartServiceCtrlDispatcherW is handed."""

    _fields_ = [("lpServiceName", ctypes.c_wchar_p), ("lpServiceProc", ctypes.c_void_p)]


class JobObjectBasicLimitInformation(ctypes.Structure):
    """JOBOBJECT_BASIC_LIMIT_INFORMATION."""

    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", DWORD),
        ("SchedulingClass", DWORD),
    ]


class IoCounters(ctypes.Structure):
    """IO_COUNTERS."""

    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JobObjectExtendedLimitInformation(ctypes.Structure):
    """JOBOBJECT_EXTENDED_LIMIT_INFORMATION, which carries the kill-on-close flag."""

    _fields_ = [
        ("BasicLimitInformation", JobObjectBasicLimitInformation),
        ("IoInfo", IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class ShellExecuteInfo(ctypes.Structure):
    """SHELLEXECUTEINFOW: what ShellExecuteExW starts, and the process it started."""

    _fields_ = [
        ("cbSize", DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", ctypes.c_void_p),
        ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p),
        ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p),
        ("hkeyClass", ctypes.c_void_p),
        ("dwHotKey", DWORD),
        ("hIconOrMonitor", ctypes.c_void_p),
        ("hProcess", ctypes.c_void_p),
    ]


class SockaddrIn(ctypes.Structure):
    """SOCKADDR_IN."""

    _fields_ = [
        ("sin_family", ctypes.c_uint16),
        ("sin_port", ctypes.c_uint16),
        ("sin_addr", ctypes.c_uint8 * 4),
        ("sin_zero", ctypes.c_uint8 * 8),
    ]


class SockaddrIn6(ctypes.Structure):
    """SOCKADDR_IN6."""

    _fields_ = [
        ("sin6_family", ctypes.c_uint16),
        ("sin6_port", ctypes.c_uint16),
        ("sin6_flowinfo", DWORD),
        ("sin6_addr", ctypes.c_uint8 * 16),
        ("sin6_scope_id", DWORD),
    ]


class SockaddrInet(ctypes.Union):
    """SOCKADDR_INET: an IPv4 or IPv6 address, told apart by its family."""

    _fields_ = [
        ("Ipv4", SockaddrIn),
        ("Ipv6", SockaddrIn6),
        ("si_family", ctypes.c_uint16),
    ]


class IpAddressPrefix(ctypes.Structure):
    """IP_ADDRESS_PREFIX."""

    _fields_ = [("Prefix", SockaddrInet), ("PrefixLength", ctypes.c_uint8)]


class MibIpForwardRow2(ctypes.Structure):
    """MIB_IPFORWARD_ROW2: one route, 104 bytes."""

    _fields_ = [
        ("InterfaceLuid", ctypes.c_uint64),
        ("InterfaceIndex", DWORD),
        ("DestinationPrefix", IpAddressPrefix),
        ("NextHop", SockaddrInet),
        ("SitePrefixLength", ctypes.c_uint8),
        ("ValidLifetime", DWORD),
        ("PreferredLifetime", DWORD),
        ("Metric", DWORD),
        ("Protocol", ctypes.c_int32),
        ("Loopback", ctypes.c_uint8),
        ("AutoconfigureAddress", ctypes.c_uint8),
        ("Publish", ctypes.c_uint8),
        ("Immortal", ctypes.c_uint8),
        ("Age", DWORD),
        ("Origin", ctypes.c_int32),
    ]


class MibIpInterfaceRow(ctypes.Structure):
    """MIB_IPINTERFACE_ROW: one interface of one address family, 168 bytes."""

    _fields_ = [
        ("Family", ctypes.c_uint16),
        ("InterfaceLuid", ctypes.c_uint64),
        ("InterfaceIndex", DWORD),
        ("MaxReassemblySize", DWORD),
        ("InterfaceIdentifier", ctypes.c_uint64),
        ("MinRouterAdvertisementInterval", DWORD),
        ("MaxRouterAdvertisementInterval", DWORD),
        ("AdvertisingEnabled", ctypes.c_uint8),
        ("ForwardingEnabled", ctypes.c_uint8),
        ("WeakHostSend", ctypes.c_uint8),
        ("WeakHostReceive", ctypes.c_uint8),
        ("UseAutomaticMetric", ctypes.c_uint8),
        ("UseNeighborUnreachabilityDetection", ctypes.c_uint8),
        ("ManagedAddressConfigurationSupported", ctypes.c_uint8),
        ("OtherStatefulConfigurationSupported", ctypes.c_uint8),
        ("AdvertiseDefaultRoute", ctypes.c_uint8),
        ("RouterDiscoveryBehavior", ctypes.c_int32),
        ("DadTransmits", DWORD),
        ("BaseReachableTime", DWORD),
        ("RetransmitTime", DWORD),
        ("PathMtuDiscoveryTimeout", DWORD),
        ("LinkLocalAddressBehavior", ctypes.c_int32),
        ("LinkLocalAddressTimeout", DWORD),
        ("ZoneIndices", DWORD * 16),
        ("SitePrefixLength", DWORD),
        ("Metric", DWORD),
        ("NlMtu", DWORD),
        ("Connected", ctypes.c_uint8),
        ("SupportsWakeUpPatterns", ctypes.c_uint8),
        ("SupportsNeighborDiscovery", ctypes.c_uint8),
        ("SupportsRouterDiscovery", ctypes.c_uint8),
        ("ReachableTime", DWORD),
        ("TransmitOffload", ctypes.c_uint8),
        ("ReceiveOffload", ctypes.c_uint8),
        ("DisableDefaultRoutes", ctypes.c_uint8),
    ]


class MibUnicastIpAddressRow(ctypes.Structure):
    """MIB_UNICASTIPADDRESS_ROW: one address an interface holds, 80 bytes."""

    _fields_ = [
        ("Address", SockaddrInet),
        ("InterfaceLuid", ctypes.c_uint64),
        ("InterfaceIndex", DWORD),
        ("PrefixOrigin", ctypes.c_int32),
        ("SuffixOrigin", ctypes.c_int32),
        ("ValidLifetime", DWORD),
        ("PreferredLifetime", DWORD),
        ("OnLinkPrefixLength", ctypes.c_uint8),
        ("SkipAsSource", ctypes.c_uint8),
        ("DadState", ctypes.c_int32),
        ("ScopeId", DWORD),
        ("CreationTimeStamp", ctypes.c_int64),
    ]


class Win32Libraries:
    """Every DLL the hub calls, with its prototypes set once.

    Handles are pointers: without these prototypes a 64-bit handle comes
    back truncated to an int.
    """

    def __init__(self):
        """
        Raises:
            OSError: When a library cannot be loaded.
        """
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self.iphlpapi = ctypes.WinDLL("iphlpapi")
        self._describe_kernel32()
        self._describe_advapi32()
        self._describe_shell32()
        self._describe_iphlpapi()

    def _describe_kernel32(self) -> None:
        """Prototype the job calls."""
        self.kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        self.kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        self.kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            DWORD,
        ]
        self.kernel32.AssignProcessToJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.kernel32.WaitForSingleObject.restype = DWORD
        self.kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, DWORD]
        self.kernel32.GetExitCodeProcess.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(DWORD),
        ]

    def _describe_advapi32(self) -> None:
        """Prototype the service calls."""
        self.advapi32.StartServiceCtrlDispatcherW.argtypes = [ctypes.c_void_p]
        self.advapi32.RegisterServiceCtrlHandlerExW.restype = ctypes.c_void_p
        self.advapi32.RegisterServiceCtrlHandlerExW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.advapi32.SetServiceStatus.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ServiceStatus),
        ]

    def _describe_shell32(self) -> None:
        """Prototype the shell32 calls."""
        self.shell32.IsUserAnAdmin.restype = ctypes.c_int
        self.shell32.IsUserAnAdmin.argtypes = []
        self.shell32.ShellExecuteExW.restype = ctypes.c_int
        self.shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]

    def _describe_iphlpapi(self) -> None:
        """Prototype the network table calls, each answering a Win32 code."""
        for name in (
            "GetIpForwardTable2",
            "GetIpInterfaceTable",
            "GetUnicastIpAddressTable",
        ):
            call = getattr(self.iphlpapi, name)
            call.restype = DWORD
            call.argtypes = [ctypes.c_uint16, ctypes.POINTER(ctypes.c_void_p)]
        self.iphlpapi.FreeMibTable.restype = None
        self.iphlpapi.FreeMibTable.argtypes = [ctypes.c_void_p]
        self.iphlpapi.ConvertInterfaceLuidToAlias.restype = DWORD
        self.iphlpapi.ConvertInterfaceLuidToAlias.argtypes = [
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        self.iphlpapi.GetAdaptersAddresses.restype = DWORD
        self.iphlpapi.GetAdaptersAddresses.argtypes = [
            DWORD,
            DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(DWORD),
        ]
