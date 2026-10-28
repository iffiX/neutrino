"""The agent's one Win32 binding: the libraries, their prototypes, the names.

Every Win32 constant the agent uses is spelled here as Win32 spells it, every
structure is declared once, and every DLL handle comes from :func:`libraries`.
Nothing binds a library at import time, so this module imports on Linux as
readily as on Windows and the seams above it stay replaceable in tests.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ctypes

# A DWORD is 32 bits on Windows; c_ulong is 64 on Linux, where the tests
# build these same structures.
DWORD = ctypes.c_uint32

# Files and handles.
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
# As the unsigned value a c_void_p restype hands back.
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# Named pipes. One instance per client, like one accepted socket per client.
PIPE_ACCESS_DUPLEX = 0x00000003
PIPE_TYPE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000
PIPE_UNLIMITED_INSTANCES = 255
PIPE_BUFFER_BYTES = 64 * 1024
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
ERROR_PIPE_CONNECTED = 535
ERROR_BROKEN_PIPE = 109
ERROR_NO_DATA = 232

# Security descriptors, at the one revision the SDDL converter takes.
SDDL_REVISION_1 = 1

# Services: the one kind this agent is, the states it reports, the controls
# it accepts and answers.
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
ERROR_FAILED_SERVICE_CONTROLLER_CONNECT = 1063

# Pseudo consoles. The attribute names the console for the process about
# to start.
PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
# The three standard handles, as GetStdHandle and SetStdHandle name them.
STD_HANDLE_NAMES = (0xFFFFFFF6, 0xFFFFFFF5, 0xFFFFFFF4)
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_SUSPENDED = 0x00000004
CREATE_NO_WINDOW = 0x08000000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
WAIT_OBJECT_0 = 0
INFINITE = 0xFFFFFFFF
# A process started with three pipes of its own: the attribute that limits
# the handles it inherits to those, the flag that hands them over, and the
# handle flag that makes one inheritable.
PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
STARTF_USESTDHANDLES = 0x00000100
HANDLE_FLAG_INHERIT = 0x00000001
# Loading an account's profile without a dialog when it cannot be loaded.
PI_NOUI = 0x00000001

# The local security policy: the access a policy handle is opened with to
# grant an account a right, and the answer a first sizing call gives.
POLICY_CREATE_ACCOUNT = 0x00000010
POLICY_LOOKUP_NAMES = 0x00000800
ERROR_INSUFFICIENT_BUFFER = 122
# The status a right's removal gets for an account that holds no right.
STATUS_OBJECT_NAME_NOT_FOUND = 0xC0000034

# Job objects: every process of a shell dies with the job's last handle, and
# a process opened by its pid is put into one with this access.
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
PROCESS_SET_QUOTA = 0x0100

# The system information classes the metrics read, and the answer a buffer
# too small for them gets.
SYSTEM_PROCESS_INFORMATION_CLASS = 5
SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION_CLASS = 8
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004

# A process's owner: the access a process and its token are opened with, and
# the token information class that names the account.
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_USER_CLASS = 1

# Ending a process: the access it is opened with, the error opening a pid
# no process holds answers, and the exit code it is ended with.
PROCESS_TERMINATE = 0x0001
ERROR_INVALID_PARAMETER = 87
TERMINATED_EXIT_CODE = 1

# Performance counters: the answer a sizing call gets, the formats asked for,
# and the item statuses that carry a value.
PDH_MORE_DATA = 0x800007D2
PDH_FMT_DOUBLE = 0x00000200
PDH_FMT_LARGE = 0x00000400
PDH_CSTATUS_VALID_DATA = 0
PDH_CSTATUS_NEW_DATA = 1

# The graphics kernel's adapter queries and the bits of the adapter's type.
KMTQAITYPE_GETSEGMENTSIZE = 3
KMTQAITYPE_ADAPTERREGISTRYINFO = 8
KMTQAITYPE_ADAPTERTYPE = 15
D3DKMT_ADAPTERTYPE_RENDER_SUPPORTED = 0x1
D3DKMT_ADAPTERTYPE_SOFTWARE_DEVICE = 0x4
D3DKMT_ADAPTERTYPE_COMPUTE_ONLY = 0x800
D3DKMT_REGISTRY_STRING_CHARS = 260

# The network tables: the address families, the adapters asked for without
# their anycast and multicast addresses, the interface types that are no
# adapter, the listening sockets with their processes, and the answer a
# buffer too small gets.
AF_UNSPEC = 0
AF_INET = 2
AF_INET6 = 23
GAA_FLAG_SKIP_ANYCAST = 0x0002
GAA_FLAG_SKIP_MULTICAST = 0x0004
GAA_FLAG_INCLUDE_GATEWAYS = 0x0080
IF_TYPE_SOFTWARE_LOOPBACK = 24
IF_TYPE_TUNNEL = 131
TCP_TABLE_OWNER_PID_LISTENER = 3
ERROR_BUFFER_OVERFLOW = 111

# The registry read from its 64-bit view whatever the process is.
KEY_WOW64_64KEY = 0x0100

# Local accounts: the normal ones, every row in one buffer, the flag of a
# disabled one, the kind of SID an account is, and a name no SID answers.
FILTER_NORMAL_ACCOUNT = 0x0002
MAX_PREFERRED_LENGTH = 0xFFFFFFFF
UF_ACCOUNTDISABLE = 0x0002
SID_TYPE_USER = 1
ERROR_NONE_MAPPED = 1332
COMPUTER_NAME_CHARS = 256

# Logons: the kinds tried for an account's files and for its terminal, the
# answer a wrong password gets, and the one a kind the account may not use
# gets.
LOGON32_LOGON_INTERACTIVE = 2
LOGON32_LOGON_BATCH = 4
LOGON32_LOGON_NETWORK_CLEARTEXT = 8
LOGON32_PROVIDER_DEFAULT = 0
ERROR_LOGON_FAILURE = 1326
ERROR_LOGON_TYPE_NOT_GRANTED = 1385

# Another process's memory: the access it is opened with, its basic
# information, and where its parameters hold the image path and the command
# line in a 64-bit process.
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_BASIC_INFORMATION_CLASS = 0
PEB_PROCESS_PARAMETERS_OFFSET = 0x20
PROCESS_PARAMETERS_IMAGE_PATH_OFFSET = 0x60
PROCESS_PARAMETERS_COMMAND_LINE_OFFSET = 0x70

# Another service's configuration: the access the manager and the service
# are opened with, and the answer for a service that is not there.
SC_MANAGER_CONNECT = 0x0001
SERVICE_QUERY_CONFIG = 0x0001
SERVICE_QUERY_STATUS = 0x0004
ERROR_SERVICE_DOES_NOT_EXIST = 1060


def last_error() -> OSError:
    """The calling thread's last Win32 error, as the OSError it is.

    Returns:
        The error; off Windows, a plain OSError naming the number.
    """
    code = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else 0
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


def kill_on_close_job(kernel32):
    """A job object that ends every process in it when its last handle closes.

    Args:
        kernel32: The bound kernel32.

    Returns:
        The job handle.

    Raises:
        OSError: When the job cannot be made or limited.
    """
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise last_error()
    limits = JobObjectExtendedLimitInformation()
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        job,
        JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    ):
        kernel32.CloseHandle(job)
        raise last_error()
    return job


def utf16_at(data: bytes, base: int, address: int) -> str:
    """The null-terminated UTF-16 string a pointer inside a buffer names.

    Args:
        data: The buffer's bytes.
        base: The address the buffer sat at, which its pointers count from.
        address: The pointer; 0 is no string.

    Returns:
        The text up to its null, or to the buffer's end; empty for a null
        pointer.

    Raises:
        ValueError: When the pointer leads outside the buffer.
    """
    if not address:
        return ""
    offset = address - base
    if offset < 0 or offset >= len(data):
        raise ValueError(f"a pointer {address:#x} outside the buffer at {base:#x}")
    end = offset
    while end + 1 < len(data) and data[end : end + 2] != b"\x00\x00":
        end += 2
    return data[offset:end].decode("utf-16-le", "replace")


_LIBRARIES = None


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
        if not hasattr(ctypes, "WinDLL"):
            raise OSError("no Win32 libraries on this system")
        _LIBRARIES = Win32Libraries()
    return _LIBRARIES


class FileTime(ctypes.Structure):
    """A count of 100-nanosecond intervals, in two halves."""

    _fields_ = [("dwLowDateTime", DWORD), ("dwHighDateTime", DWORD)]

    @property
    def value(self) -> int:
        """The count, whole."""
        return (self.dwHighDateTime << 32) | self.dwLowDateTime


class MemoryStatusEx(ctypes.Structure):
    """What GlobalMemoryStatusEx fills in."""

    _fields_ = [
        ("dwLength", DWORD),
        ("dwMemoryLoad", DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class SecurityAttributes(ctypes.Structure):
    """SECURITY_ATTRIBUTES: a pipe instance's access, or an inheritable handle."""

    _fields_ = [
        ("nLength", DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", ctypes.c_int),
    ]


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


class Coord(ctypes.Structure):
    """A console size."""

    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class StartupInfo(ctypes.Structure):
    """What a new process is started with."""

    _fields_ = [
        ("cb", DWORD),
        ("lpReserved", ctypes.c_wchar_p),
        ("lpDesktop", ctypes.c_wchar_p),
        ("lpTitle", ctypes.c_wchar_p),
        ("dwX", DWORD),
        ("dwY", DWORD),
        ("dwXSize", DWORD),
        ("dwYSize", DWORD),
        ("dwXCountChars", DWORD),
        ("dwYCountChars", DWORD),
        ("dwFillAttribute", DWORD),
        ("dwFlags", DWORD),
        ("wShowWindow", ctypes.c_ushort),
        ("cbReserved2", ctypes.c_ushort),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", ctypes.c_void_p),
        ("hStdOutput", ctypes.c_void_p),
        ("hStdError", ctypes.c_void_p),
    ]


class ProfileInfo(ctypes.Structure):
    """PROFILEINFOW, what loading an account's profile takes and gives."""

    _fields_ = [
        ("dwSize", DWORD),
        ("dwFlags", DWORD),
        ("lpUserName", ctypes.c_wchar_p),
        ("lpProfilePath", ctypes.c_wchar_p),
        ("lpDefaultPath", ctypes.c_wchar_p),
        ("lpServerName", ctypes.c_wchar_p),
        ("lpPolicyPath", ctypes.c_wchar_p),
        ("hProfile", ctypes.c_void_p),
    ]


class StartupInfoEx(ctypes.Structure):
    """A startup record with an attribute list, for the pseudo console."""

    _fields_ = [("StartupInfo", StartupInfo), ("lpAttributeList", ctypes.c_void_p)]


class ProcessInformation(ctypes.Structure):
    """What a started process is known by."""

    _fields_ = [
        ("hProcess", ctypes.c_void_p),
        ("hThread", ctypes.c_void_p),
        ("dwProcessId", DWORD),
        ("dwThreadId", DWORD),
    ]


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


class LsaUnicodeString(ctypes.Structure):
    """LSA_UNICODE_STRING: a UTF-16 string by its length in bytes."""

    _fields_ = [
        ("Length", ctypes.c_ushort),
        ("MaximumLength", ctypes.c_ushort),
        ("Buffer", ctypes.c_void_p),
    ]


class LsaObjectAttributes(ctypes.Structure):
    """LSA_OBJECT_ATTRIBUTES, all zero but its length."""

    _fields_ = [
        ("Length", DWORD),
        ("RootDirectory", ctypes.c_void_p),
        ("ObjectName", ctypes.c_void_p),
        ("Attributes", DWORD),
        ("SecurityDescriptor", ctypes.c_void_p),
        ("SecurityQualityOfService", ctypes.c_void_p),
    ]


class SystemProcessorPerformanceInformation(ctypes.Structure):
    """SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION: one core's times."""

    _fields_ = [
        ("IdleTime", ctypes.c_int64),
        ("KernelTime", ctypes.c_int64),
        ("UserTime", ctypes.c_int64),
        ("DpcTime", ctypes.c_int64),
        ("InterruptTime", ctypes.c_int64),
        ("InterruptCount", DWORD),
    ]


class UnicodeString(ctypes.Structure):
    """UNICODE_STRING: UTF-16 by its length in bytes."""

    _fields_ = [
        ("Length", ctypes.c_ushort),
        ("MaximumLength", ctypes.c_ushort),
        ("Buffer", ctypes.c_void_p),
    ]


class SystemProcessInformation(ctypes.Structure):
    """SYSTEM_PROCESS_INFORMATION, up to the working set."""

    _fields_ = [
        ("NextEntryOffset", DWORD),
        ("NumberOfThreads", DWORD),
        ("WorkingSetPrivateSize", ctypes.c_int64),
        ("HardFaultCount", DWORD),
        ("NumberOfThreadsHighWatermark", DWORD),
        ("CycleTime", ctypes.c_uint64),
        ("CreateTime", ctypes.c_int64),
        ("UserTime", ctypes.c_int64),
        ("KernelTime", ctypes.c_int64),
        ("ImageName", UnicodeString),
        ("BasePriority", ctypes.c_int32),
        ("UniqueProcessId", ctypes.c_void_p),
        ("InheritedFromUniqueProcessId", ctypes.c_void_p),
        ("HandleCount", DWORD),
        ("SessionId", DWORD),
        ("UniqueProcessKey", ctypes.c_size_t),
        ("PeakVirtualSize", ctypes.c_size_t),
        ("VirtualSize", ctypes.c_size_t),
        ("PageFaultCount", DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
    ]


class SidAndAttributes(ctypes.Structure):
    """SID_AND_ATTRIBUTES, the head of what TokenUser answers."""

    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", DWORD)]


class PdhFmtCounterValueUnion(ctypes.Union):
    """The value half of PDH_FMT_COUNTERVALUE."""

    _fields_ = [
        ("longValue", ctypes.c_int32),
        ("doubleValue", ctypes.c_double),
        ("largeValue", ctypes.c_int64),
        ("AnsiStringValue", ctypes.c_char_p),
        ("WideStringValue", ctypes.c_wchar_p),
    ]


class PdhFmtCounterValue(ctypes.Structure):
    """PDH_FMT_COUNTERVALUE."""

    _fields_ = [("CStatus", DWORD), ("value", PdhFmtCounterValueUnion)]


class PdhFmtCounterValueItem(ctypes.Structure):
    """PDH_FMT_COUNTERVALUE_ITEM_W: one instance of a wildcard counter."""

    _fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", PdhFmtCounterValue)]


class Luid(ctypes.Structure):
    """LUID: an adapter's id for this boot."""

    _fields_ = [("LowPart", DWORD), ("HighPart", ctypes.c_int32)]


class D3dkmtAdapterInfo(ctypes.Structure):
    """D3DKMT_ADAPTERINFO: one adapter the graphics kernel lists."""

    _fields_ = [
        ("hAdapter", ctypes.c_uint32),
        ("AdapterLuid", Luid),
        ("NumOfSources", ctypes.c_uint32),
        ("bPrecisePresentRegionsPreferred", ctypes.c_int32),
    ]


class D3dkmtEnumAdapters2(ctypes.Structure):
    """D3DKMT_ENUMADAPTERS2: the count, then the adapters."""

    _fields_ = [("NumAdapters", ctypes.c_uint32), ("pAdapters", ctypes.c_void_p)]


class D3dkmtQueryAdapterInfo(ctypes.Structure):
    """D3DKMT_QUERYADAPTERINFO: one question about one adapter."""

    _fields_ = [
        ("hAdapter", ctypes.c_uint32),
        ("Type", ctypes.c_uint32),
        ("pPrivateDriverData", ctypes.c_void_p),
        ("PrivateDriverDataSize", ctypes.c_uint32),
    ]


class D3dkmtAdapterRegistryInfo(ctypes.Structure):
    """D3DKMT_ADAPTERREGISTRYINFO, its strings as UTF-16 units."""

    _fields_ = [
        ("AdapterString", ctypes.c_uint16 * D3DKMT_REGISTRY_STRING_CHARS),
        ("BiosString", ctypes.c_uint16 * D3DKMT_REGISTRY_STRING_CHARS),
        ("DacType", ctypes.c_uint16 * D3DKMT_REGISTRY_STRING_CHARS),
        ("ChipType", ctypes.c_uint16 * D3DKMT_REGISTRY_STRING_CHARS),
    ]


class D3dkmtSegmentSizeInfo(ctypes.Structure):
    """D3DKMT_SEGMENTSIZEINFO: the adapter's memory by kind."""

    _fields_ = [
        ("DedicatedVideoMemorySize", ctypes.c_uint64),
        ("DedicatedSystemMemorySize", ctypes.c_uint64),
        ("SharedSystemMemorySize", ctypes.c_uint64),
    ]


class D3dkmtCloseAdapter(ctypes.Structure):
    """D3DKMT_CLOSEADAPTER."""

    _fields_ = [("hAdapter", ctypes.c_uint32)]


class SocketAddress(ctypes.Structure):
    """SOCKET_ADDRESS, its pointer as a 64-bit address."""

    _fields_ = [("lpSockaddr", ctypes.c_uint64), ("iSockaddrLength", ctypes.c_int32)]


class IpAdapterAddresses(ctypes.Structure):
    """IP_ADAPTER_ADDRESSES_LH up to its LUID, pointers as 64-bit addresses."""

    _fields_ = [
        ("Length", ctypes.c_uint32),
        ("IfIndex", ctypes.c_uint32),
        ("Next", ctypes.c_uint64),
        ("AdapterName", ctypes.c_uint64),
        ("FirstUnicastAddress", ctypes.c_uint64),
        ("FirstAnycastAddress", ctypes.c_uint64),
        ("FirstMulticastAddress", ctypes.c_uint64),
        ("FirstDnsServerAddress", ctypes.c_uint64),
        ("DnsSuffix", ctypes.c_uint64),
        ("Description", ctypes.c_uint64),
        ("FriendlyName", ctypes.c_uint64),
        ("PhysicalAddress", ctypes.c_uint8 * 8),
        ("PhysicalAddressLength", ctypes.c_uint32),
        ("Flags", ctypes.c_uint32),
        ("Mtu", ctypes.c_uint32),
        ("IfType", ctypes.c_uint32),
        ("OperStatus", ctypes.c_int32),
        ("Ipv6IfIndex", ctypes.c_uint32),
        ("ZoneIndices", ctypes.c_uint32 * 16),
        ("FirstPrefix", ctypes.c_uint64),
        ("TransmitLinkSpeed", ctypes.c_uint64),
        ("ReceiveLinkSpeed", ctypes.c_uint64),
        ("FirstWinsServerAddress", ctypes.c_uint64),
        ("FirstGatewayAddress", ctypes.c_uint64),
        ("Ipv4Metric", ctypes.c_uint32),
        ("Ipv6Metric", ctypes.c_uint32),
        ("Luid", ctypes.c_uint64),
    ]


class IpAdapterUnicastAddress(ctypes.Structure):
    """IP_ADAPTER_UNICAST_ADDRESS_LH, pointers as 64-bit addresses."""

    _fields_ = [
        ("Length", ctypes.c_uint32),
        ("Flags", ctypes.c_uint32),
        ("Next", ctypes.c_uint64),
        ("Address", SocketAddress),
        ("PrefixOrigin", ctypes.c_int32),
        ("SuffixOrigin", ctypes.c_int32),
        ("DadState", ctypes.c_int32),
        ("ValidLifetime", ctypes.c_uint32),
        ("PreferredLifetime", ctypes.c_uint32),
        ("LeaseLifetime", ctypes.c_uint32),
        ("OnLinkPrefixLength", ctypes.c_uint8),
    ]


class MibTcpRowOwnerPid(ctypes.Structure):
    """MIB_TCPROW_OWNER_PID: one IPv4 socket, its port in network order."""

    _fields_ = [
        ("dwState", ctypes.c_uint32),
        ("dwLocalAddr", ctypes.c_uint32),
        ("dwLocalPort", ctypes.c_uint32),
        ("dwRemoteAddr", ctypes.c_uint32),
        ("dwRemotePort", ctypes.c_uint32),
        ("dwOwningPid", ctypes.c_uint32),
    ]


class MibTcp6RowOwnerPid(ctypes.Structure):
    """MIB_TCP6ROW_OWNER_PID: one IPv6 socket, its port in network order."""

    _fields_ = [
        ("ucLocalAddr", ctypes.c_uint8 * 16),
        ("dwLocalScopeId", ctypes.c_uint32),
        ("dwLocalPort", ctypes.c_uint32),
        ("ucRemoteAddr", ctypes.c_uint8 * 16),
        ("dwRemoteScopeId", ctypes.c_uint32),
        ("dwRemotePort", ctypes.c_uint32),
        ("dwState", ctypes.c_uint32),
        ("dwOwningPid", ctypes.c_uint32),
    ]


class UserInfo1(ctypes.Structure):
    """USER_INFO_1, pointers as 64-bit addresses."""

    _fields_ = [
        ("usri1_name", ctypes.c_uint64),
        ("usri1_password", ctypes.c_uint64),
        ("usri1_password_age", ctypes.c_uint32),
        ("usri1_priv", ctypes.c_uint32),
        ("usri1_home_dir", ctypes.c_uint64),
        ("usri1_comment", ctypes.c_uint64),
        ("usri1_flags", ctypes.c_uint32),
        ("usri1_script_path", ctypes.c_uint64),
    ]


class ProcessBasicInformation(ctypes.Structure):
    """PROCESS_BASIC_INFORMATION of a 64-bit process."""

    _fields_ = [
        ("ExitStatus", ctypes.c_int32),
        ("PebBaseAddress", ctypes.c_uint64),
        ("AffinityMask", ctypes.c_uint64),
        ("BasePriority", ctypes.c_int32),
        ("UniqueProcessId", ctypes.c_uint64),
        ("InheritedFromUniqueProcessId", ctypes.c_uint64),
    ]


class QueryServiceConfig(ctypes.Structure):
    """QUERY_SERVICE_CONFIGW, pointers as 64-bit addresses."""

    _fields_ = [
        ("dwServiceType", ctypes.c_uint32),
        ("dwStartType", ctypes.c_uint32),
        ("dwErrorControl", ctypes.c_uint32),
        ("lpBinaryPathName", ctypes.c_uint64),
        ("lpLoadOrderGroup", ctypes.c_uint64),
        ("dwTagId", ctypes.c_uint32),
        ("lpDependencies", ctypes.c_uint64),
        ("lpServiceStartName", ctypes.c_uint64),
        ("lpDisplayName", ctypes.c_uint64),
    ]


class Win32Libraries:
    """Every DLL the agent calls, with its prototypes set once.

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
        self.wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
        self.ntdll = ctypes.WinDLL("ntdll")
        self.pdh = ctypes.WinDLL("pdh")
        self.gdi32 = ctypes.WinDLL("gdi32")
        self.iphlpapi = ctypes.WinDLL("iphlpapi")
        self.netapi32 = ctypes.WinDLL("netapi32")
        self.userenv = ctypes.WinDLL("userenv", use_last_error=True)
        self._describe_kernel32()
        self._describe_advapi32()
        self._describe_shell32()
        self._describe_wtsapi32()
        self._describe_metrics()
        self._describe_network()
        self._describe_accounts()
        self._describe_processes()
        self._describe_services()

    def _describe_kernel32(self) -> None:
        """Prototype the kernel32 calls."""
        self.kernel32.GetSystemTimes.argtypes = [
            ctypes.POINTER(FileTime),
            ctypes.POINTER(FileTime),
            ctypes.POINTER(FileTime),
        ]
        self.kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatusEx)]
        self.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        self.kernel32.GetTickCount64.argtypes = []
        self.kernel32.CreateNamedPipeW.restype = ctypes.c_void_p
        self.kernel32.CreateNamedPipeW.argtypes = [
            ctypes.c_wchar_p,
            DWORD,
            DWORD,
            DWORD,
            DWORD,
            DWORD,
            DWORD,
            ctypes.c_void_p,
        ]
        self.kernel32.CreateFileW.restype = ctypes.c_void_p
        self.kernel32.CreateFileW.argtypes = [
            ctypes.c_wchar_p,
            DWORD,
            DWORD,
            ctypes.c_void_p,
            DWORD,
            DWORD,
            ctypes.c_void_p,
        ]
        for name in (
            "FlushFileBuffers",
            "DisconnectNamedPipe",
            "CloseHandle",
            "LocalFree",
        ):
            getattr(self.kernel32, name).argtypes = [ctypes.c_void_p]
        self.kernel32.ConnectNamedPipe.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.kernel32.ReadFile.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.kernel32.WriteFile.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]

        self._describe_console()

    def _describe_console(self) -> None:
        """Prototype the pseudo console, process and job calls."""
        self.kernel32.CreatePipe.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
            DWORD,
        ]
        self.kernel32.WaitForSingleObject.restype = DWORD
        self.kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, DWORD]
        self.kernel32.GetExitCodeProcess.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(DWORD),
        ]
        self.kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        self.kernel32.ResumeThread.restype = DWORD
        self.kernel32.ResumeThread.argtypes = [ctypes.c_void_p]
        self.kernel32.InitializeProcThreadAttributeList.argtypes = [
            ctypes.c_void_p,
            DWORD,
            DWORD,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self.kernel32.UpdateProcThreadAttribute.argtypes = [
            ctypes.c_void_p,
            DWORD,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.kernel32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
        self.kernel32.GetStdHandle.restype = ctypes.c_void_p
        self.kernel32.GetStdHandle.argtypes = [DWORD]
        self.kernel32.SetStdHandle.argtypes = [DWORD, ctypes.c_void_p]
        self.kernel32.CreateProcessW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            DWORD,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.POINTER(ProcessInformation),
        ]
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
        # The pseudo console calls are absent before Windows 10 1809; the
        # shell stream checks for them before using them.
        if hasattr(self.kernel32, "CreatePseudoConsole"):
            self.kernel32.CreatePseudoConsole.restype = ctypes.c_long
            self.kernel32.CreatePseudoConsole.argtypes = [
                Coord,
                ctypes.c_void_p,
                ctypes.c_void_p,
                DWORD,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            self.kernel32.ResizePseudoConsole.restype = ctypes.c_long
            self.kernel32.ResizePseudoConsole.argtypes = [ctypes.c_void_p, Coord]
            self.kernel32.ClosePseudoConsole.argtypes = [ctypes.c_void_p]

    def _describe_advapi32(self) -> None:
        """Prototype the advapi32 calls."""
        self.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            ctypes.c_wchar_p,
            DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
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
        self.advapi32.LookupAccountNameW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.POINTER(DWORD),
            ctypes.c_void_p,
            ctypes.POINTER(DWORD),
            ctypes.POINTER(DWORD),
        ]
        self.advapi32.LsaOpenPolicy.restype = DWORD
        self.advapi32.LsaOpenPolicy.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(LsaObjectAttributes),
            DWORD,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.advapi32.LsaAddAccountRights.restype = DWORD
        self.advapi32.LsaAddAccountRights.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(LsaUnicodeString),
            DWORD,
        ]
        self.advapi32.LsaRemoveAccountRights.restype = DWORD
        self.advapi32.LsaRemoveAccountRights.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ubyte,
            ctypes.POINTER(LsaUnicodeString),
            DWORD,
        ]
        self.advapi32.LsaClose.restype = DWORD
        self.advapi32.LsaClose.argtypes = [ctypes.c_void_p]
        self.advapi32.LsaNtStatusToWinError.restype = DWORD
        self.advapi32.LsaNtStatusToWinError.argtypes = [DWORD]

    def _describe_shell32(self) -> None:
        """Prototype the shell32 calls."""
        self.shell32.IsUserAnAdmin.restype = ctypes.c_int
        self.shell32.IsUserAnAdmin.argtypes = []

    def _describe_wtsapi32(self) -> None:
        """Prototype the session calls."""
        self.kernel32.WTSGetActiveConsoleSessionId.restype = DWORD
        self.kernel32.WTSGetActiveConsoleSessionId.argtypes = []
        self.wtsapi32.WTSQuerySessionInformationW.argtypes = [
            ctypes.c_void_p,
            DWORD,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_wchar_p),
            ctypes.POINTER(DWORD),
        ]
        self.wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]

    def _describe_metrics(self) -> None:
        """Prototype the calls the metrics read beyond kernel32's own."""
        self.ntdll.NtQuerySystemInformation.restype = DWORD
        self.ntdll.NtQuerySystemInformation.argtypes = [
            DWORD,
            ctypes.c_void_p,
            DWORD,
            ctypes.POINTER(DWORD),
        ]
        self.kernel32.OpenProcess.restype = ctypes.c_void_p
        self.kernel32.OpenProcess.argtypes = [DWORD, ctypes.c_int, DWORD]
        self.advapi32.OpenProcessToken.argtypes = [
            ctypes.c_void_p,
            DWORD,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.advapi32.GetTokenInformation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            DWORD,
            ctypes.POINTER(DWORD),
        ]
        self.advapi32.GetLengthSid.restype = DWORD
        self.advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
        self.advapi32.LookupAccountSidW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.POINTER(DWORD),
            ctypes.c_wchar_p,
            ctypes.POINTER(DWORD),
            ctypes.POINTER(DWORD),
        ]
        self.pdh.PdhOpenQueryW.restype = DWORD
        self.pdh.PdhOpenQueryW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.pdh.PdhAddEnglishCounterW.restype = DWORD
        self.pdh.PdhAddEnglishCounterW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.pdh.PdhCollectQueryData.restype = DWORD
        self.pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
        self.pdh.PdhGetFormattedCounterArrayW.restype = DWORD
        self.pdh.PdhGetFormattedCounterArrayW.argtypes = [
            ctypes.c_void_p,
            DWORD,
            ctypes.POINTER(DWORD),
            ctypes.POINTER(DWORD),
            ctypes.c_void_p,
        ]
        self.pdh.PdhCloseQuery.restype = DWORD
        self.pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]
        # The adapter calls are absent before Windows 8; the GPU read checks
        # for them before using them.
        if hasattr(self.gdi32, "D3DKMTEnumAdapters2"):
            self.gdi32.D3DKMTEnumAdapters2.restype = DWORD
            self.gdi32.D3DKMTEnumAdapters2.argtypes = [
                ctypes.POINTER(D3dkmtEnumAdapters2)
            ]
            self.gdi32.D3DKMTQueryAdapterInfo.restype = DWORD
            self.gdi32.D3DKMTQueryAdapterInfo.argtypes = [
                ctypes.POINTER(D3dkmtQueryAdapterInfo)
            ]
            self.gdi32.D3DKMTCloseAdapter.restype = DWORD
            self.gdi32.D3DKMTCloseAdapter.argtypes = [
                ctypes.POINTER(D3dkmtCloseAdapter)
            ]

    def _describe_network(self) -> None:
        """Prototype the iphlpapi calls."""
        self.iphlpapi.GetAdaptersAddresses.restype = DWORD
        self.iphlpapi.GetAdaptersAddresses.argtypes = [
            DWORD,
            DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(DWORD),
        ]
        self.iphlpapi.GetExtendedTcpTable.restype = DWORD
        self.iphlpapi.GetExtendedTcpTable.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(DWORD),
            ctypes.c_int,
            DWORD,
            ctypes.c_int,
            DWORD,
        ]

    def _describe_accounts(self) -> None:
        """Prototype the local account, SID and logon calls."""
        self.netapi32.NetUserEnum.restype = DWORD
        self.netapi32.NetUserEnum.argtypes = [
            ctypes.c_wchar_p,
            DWORD,
            DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            DWORD,
            ctypes.POINTER(DWORD),
            ctypes.POINTER(DWORD),
            ctypes.POINTER(DWORD),
        ]
        self.netapi32.NetApiBufferSize.restype = DWORD
        self.netapi32.NetApiBufferSize.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(DWORD),
        ]
        self.netapi32.NetApiBufferFree.restype = DWORD
        self.netapi32.NetApiBufferFree.argtypes = [ctypes.c_void_p]
        self.advapi32.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.advapi32.LogonUserW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            DWORD,
            DWORD,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.advapi32.ImpersonateLoggedOnUser.argtypes = [ctypes.c_void_p]
        self.advapi32.RevertToSelf.argtypes = []
        self.advapi32.CreateProcessAsUserW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            DWORD,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.POINTER(ProcessInformation),
        ]
        self.userenv.LoadUserProfileW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ProfileInfo),
        ]
        self.userenv.UnloadUserProfile.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.userenv.CreateEnvironmentBlock.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self.userenv.DestroyEnvironmentBlock.argtypes = [ctypes.c_void_p]
        self.kernel32.SetHandleInformation.argtypes = [ctypes.c_void_p, DWORD, DWORD]
        self.kernel32.GetComputerNameW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.POINTER(DWORD),
        ]

    def _describe_processes(self) -> None:
        """Prototype the calls that read another process's parameters."""
        self.ntdll.NtQueryInformationProcess.restype = DWORD
        self.ntdll.NtQueryInformationProcess.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            DWORD,
            ctypes.POINTER(DWORD),
        ]
        self.kernel32.ReadProcessMemory.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]

    def _describe_services(self) -> None:
        """Prototype the calls that read another service's configuration."""
        self.advapi32.OpenSCManagerW.restype = ctypes.c_void_p
        self.advapi32.OpenSCManagerW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            DWORD,
        ]
        self.advapi32.OpenServiceW.restype = ctypes.c_void_p
        self.advapi32.OpenServiceW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            DWORD,
        ]
        self.advapi32.QueryServiceConfigW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            DWORD,
            ctypes.POINTER(DWORD),
        ]
        self.advapi32.QueryServiceStatus.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ServiceStatus),
        ]
        self.advapi32.CloseServiceHandle.argtypes = [ctypes.c_void_p]
