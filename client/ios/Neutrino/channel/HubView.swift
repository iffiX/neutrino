import Foundation

/// One hub as every page reads it: the binding, where its session stands, what its last state published, and
/// the jobs running on it.
struct HubView: Equatable, Identifiable {
    /// The binding as kept.
    var binding: HubBinding

    /// Where the session stands.
    var connection: HubConnection = .connecting

    /// What the row waits for while `connection` is waiting, nil otherwise.
    var waitReason: HubWaitReason?

    /// The code behind `waitReason`, nil when none came with it.
    var waitRefusal: ClientError?

    /// When the next round starts, in wall seconds; 0 when no countdown runs.
    var nextRoundAt: Double = 0

    /// What the hub's welcome named, such as `neutrino_hub/0.6.0`.
    var software = ""

    /// The published list.
    var services: [ChannelServiceEntry] = []

    /// The apps the published `web`, `port` and `ssh` entries belong to.
    var apps: [ChannelApp] = []

    /// The machines this phone may open a shell on.
    var terminals: [ChannelTerminal] = []

    /// The address the open session runs on, empty while down.
    var connectedAddress = ""

    /// Whether the hub welcomed this phone since the app started.
    var hasConnected = false

    /// The actions running on the hub.
    var jobs = HubJobs()

    /// The code of the row's last failed action, kept until the next press on the row or a refresh.
    var jobError: ClientError?

    /// The way the session reached the hub as its last state named it, empty before the first.
    var reachedThrough = ""

    /// The last round trip from this phone's ping to the hub's pong, in milliseconds; nil before the first pong
    /// and while the session is not open.
    var rttMs: Int?

    /// Whether the hub's last state lets this phone open its panel.
    var isPanelAllowed = false

    /// The binding's id, as a list keys the row.
    var id: String { binding.id }

    /// Whether the session is open and the hub serves this phone.
    var isConnected: Bool { connection == .connected }

    /// Whether nothing runs any more and Leave is the row's one action.
    var isLeaveOnly: Bool { waitReason == .joinRefused || waitReason == .unknownDevice }

    /// Whether the hub switched this client off.
    var isDisabled: Bool { waitReason == .disabled }

    /// The published entries of one type, empty unless the hub serves this phone.
    ///
    /// - Parameter type: `web`, `port`, `ai`, `file` or `rdp`.
    /// - Returns: The entries.
    func services(of type: String) -> [ChannelServiceEntry] {
        isConnected ? services.filter { $0.type == type } : []
    }
}
