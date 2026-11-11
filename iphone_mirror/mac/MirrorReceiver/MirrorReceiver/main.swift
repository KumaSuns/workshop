import AppKit
import AVFoundation
import Darwin
import Foundation

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var window: NSWindow!
    private var content: MirrorContentView!
    private let session = MirrorSession()
    private var publisher: NetService?
    private var appliedAspect: CGFloat = 0
    private var latestImage: NSImage?
    private var displayBusy = false
    private let displayLock = NSLock()

    func applicationDidFinishLaunching(_ notification: Notification) {
        let content = MirrorContentView(frame: NSRect(x: 0, y: 0, width: 1064, height: 608))
        self.content = content
        content.panel.onChange = { [weak self] in
            guard let self else { return }
            self.session.setOutput(volume: content.panel.volume, muted: content.panel.muted)
        }

        window = NSWindow(
            contentRect: content.frame,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "画面受信"
        window.contentView = content
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        session.onStatus = { [weak self] text in
            DispatchQueue.main.async {
                self?.content.statusLabel.stringValue = text
            }
        }
        session.onFrame = { [weak self] image in
            self?.enqueue(image)
        }
        session.start()
        let publisher = NetService(domain: "local.", type: "_mirrdev._tcp.", name: "このMac", port: 47777)
        publisher.publish()
        self.publisher = publisher
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    private func enqueue(_ image: NSImage) {
        displayLock.lock()
        latestImage = image
        let start = !displayBusy
        displayBusy = true
        displayLock.unlock()
        guard start else { return }
        DispatchQueue.main.async { [weak self] in
            self?.drainFrames()
        }
    }

    private func drainFrames() {
        while true {
            displayLock.lock()
            let image = latestImage
            latestImage = nil
            if image == nil {
                displayBusy = false
                displayLock.unlock()
                return
            }
            displayLock.unlock()
            if let image {
                show(image)
            }
        }
    }

    private func show(_ image: NSImage) {
        content.imageView.image = image
        content.statusLabel.stringValue = "受信中"
        let size = image.size
        guard size.width > 1, size.height > 1 else { return }
        let aspect = size.width / size.height
        guard abs(aspect - appliedAspect) > 0.02 else { return }
        appliedAspect = aspect
        let visible = window.screen?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1280, height: 800)
        let scale = min(visible.width * 0.72 / size.width, visible.height * 0.86 / size.height, 1)
        let picture = NSSize(width: (size.width * scale).rounded(), height: (size.height * scale).rounded())
        let fitted = NSSize(
            width: picture.width + content.panelWidth,
            height: picture.height + content.statusHeight
        )
        window.contentAspectRatio = fitted
        var frame = window.frameRect(forContentRect: NSRect(origin: .zero, size: fitted))
        frame.origin.x = visible.midX - frame.width / 2
        frame.origin.y = visible.midY - frame.height / 2
        window.setFrame(frame, display: true, animate: false)
    }
}

final class MirrorContentView: NSView {
    let panelWidth: CGFloat = 104
    let statusHeight: CGFloat = 32
    let imageView = NSImageView()
    let statusLabel = NSTextField(labelWithString: "待っています")
    let panel = GameAudioPanel()

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        layer?.backgroundColor = NSColor(srgbRed: 8 / 255, green: 12 / 255, blue: 22 / 255, alpha: 1).cgColor
        imageView.imageScaling = .scaleProportionallyUpOrDown
        imageView.imageAlignment = .alignCenter
        imageView.wantsLayer = true
        imageView.layer?.backgroundColor = layer?.backgroundColor
        statusLabel.textColor = NSColor(srgbRed: 190 / 255, green: 255 / 255, blue: 236 / 255, alpha: 1)
        statusLabel.font = NSFont.boldSystemFont(ofSize: 13)
        addSubview(imageView)
        addSubview(panel)
        addSubview(statusLabel)
        resizeSubviews(withOldSize: .zero)
    }

    required init?(coder: NSCoder) {
        nil
    }

    override func resizeSubviews(withOldSize oldSize: NSSize) {
        super.resizeSubviews(withOldSize: oldSize)
        let width = bounds.width
        let height = bounds.height
        panel.frame = NSRect(x: width - panelWidth, y: statusHeight, width: panelWidth, height: max(0, height - statusHeight))
        imageView.frame = NSRect(x: 0, y: statusHeight, width: max(0, width - panelWidth), height: max(0, height - statusHeight))
        statusLabel.frame = NSRect(x: 12, y: 6, width: max(0, width - 24), height: 20)
    }
}

final class MirrorSession {
    var onStatus: ((String) -> Void)?
    var onFrame: ((NSImage) -> Void)?

    private let audio = PcmPlayer()
    private var listenFd: Int32 = -1
    private var beaconFd: Int32 = -1
    private let queue = DispatchQueue(label: "mirror.receive")
    private let beaconQueue = DispatchQueue(label: "mirror.beacon")
    private var running = true

    func setOutput(volume: Int, muted: Bool) {
        audio.setOutput(volume: volume, muted: muted)
    }

    func start() {
        queue.async { [weak self] in
            self?.run()
        }
    }

    private func run() {
        let listen = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP)
        guard listen >= 0 else {
            onStatus?("待受を開けませんでした")
            return
        }
        var reuse: Int32 = 1
        setsockopt(listen, SOL_SOCKET, SO_REUSEADDR, &reuse, socklen_t(MemoryLayout<Int32>.size))
        var addr = sockaddr_in()
        addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = UInt16(47777).bigEndian
        addr.sin_addr.s_addr = INADDR_ANY
        let bound = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(listen, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        guard bound == 0, Darwin.listen(listen, 1) == 0 else {
            onStatus?("待受を開けませんでした")
            close(listen)
            return
        }
        listenFd = listen

        let beacon = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
        if beacon >= 0 {
            var broadcast: Int32 = 1
            setsockopt(beacon, SOL_SOCKET, SO_BROADCAST, &broadcast, socklen_t(MemoryLayout<Int32>.size))
            beaconFd = beacon
        }
        onStatus?("iPhone からの画面を待っています")
        beaconQueue.async { [weak self] in
            self?.beaconLoop()
        }
        acceptLoop()
    }

    private func acceptLoop() {
        while running {
            var clientAddr = sockaddr_in()
            var length = socklen_t(MemoryLayout<sockaddr_in>.size)
            let client = withUnsafeMutablePointer(to: &clientAddr) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    accept(listenFd, $0, &length)
                }
            }
            if client < 0 { continue }
            var nodelay: Int32 = 1
            setsockopt(client, IPPROTO_TCP, TCP_NODELAY, &nodelay, socklen_t(MemoryLayout<Int32>.size))
            readClient(client)
            close(client)
            if running {
                onStatus?("iPhone からの画面を待っています")
            }
        }
    }

    private func readClient(_ fd: Int32) {
        while running {
            guard let lengthData = readExact(fd, count: 4) else { return }
            let length = Int(lengthData.withUnsafeBytes { $0.load(as: UInt32.self).bigEndian })
            guard length >= 1, length <= 4_000_000, let body = readExact(fd, count: length) else { return }
            let type = body[body.startIndex]
            let payload = body.subdata(in: body.index(after: body.startIndex)..<body.endIndex)
            switch type {
            case 1:
                if let image = NSImage(data: payload) {
                    onFrame?(image)
                }
            case 2:
                audio.play(payload)
            default:
                break
            }
        }
    }

    private func readExact(_ fd: Int32, count: Int) -> Data? {
        var data = Data(count: count)
        var offset = 0
        let ok = data.withUnsafeMutableBytes { raw -> Bool in
            guard let base = raw.baseAddress else { return false }
            while offset < count {
                let read = recv(fd, base.advanced(by: offset), count - offset, 0)
                if read <= 0 { return false }
                offset += read
            }
            return true
        }
        return ok ? data : nil
    }

    private func beaconLoop() {
        var packet = Data("MIRR".utf8)
        var port = UInt16(47777).bigEndian
        withUnsafeBytes(of: &port) { packet.append(contentsOf: $0) }
        packet.append(contentsOf: "このMac".utf8)
        while running {
            for address in broadcastAddresses() {
                var dest = sockaddr_in()
                dest.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
                dest.sin_family = sa_family_t(AF_INET)
                dest.sin_port = UInt16(47778).bigEndian
                dest.sin_addr = address
                _ = packet.withUnsafeBytes { raw in
                    withUnsafePointer(to: &dest) {
                        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                            sendto(beaconFd, raw.baseAddress, raw.count, 0, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
                        }
                    }
                }
            }
            Thread.sleep(forTimeInterval: 1)
        }
    }

    private func broadcastAddresses() -> [in_addr] {
        var addresses: [in_addr] = []
        var global = in_addr()
        inet_pton(AF_INET, "255.255.255.255", &global)
        addresses.append(global)

        var pointer: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&pointer) == 0, let first = pointer else { return addresses }
        defer { freeifaddrs(first) }
        var cursor: UnsafeMutablePointer<ifaddrs>? = first
        while let item = cursor {
            let iface = item.pointee
            if iface.ifa_flags & UInt32(IFF_UP) != 0,
               iface.ifa_flags & UInt32(IFF_LOOPBACK) == 0,
               let addr = iface.ifa_addr,
               addr.pointee.sa_family == sa_family_t(AF_INET),
               let netmask = iface.ifa_netmask {
                let ip = addr.withMemoryRebound(to: sockaddr_in.self, capacity: 1) { $0.pointee.sin_addr }
                let mask = netmask.withMemoryRebound(to: sockaddr_in.self, capacity: 1) { $0.pointee.sin_addr }
                var broadcast = in_addr()
                broadcast.s_addr = ip.s_addr | ~mask.s_addr
                addresses.append(broadcast)
            }
            cursor = iface.ifa_next
        }
        return addresses
    }
}

final class PcmPlayer {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var format: AVAudioFormat?
    private var started = false
    private var attached = false
    private var gain: Float = 1

    func setOutput(volume: Int, muted: Bool) {
        gain = muted ? 0 : Float(volume) / 100
        let apply = { [weak self] in
            self?.player.volume = self?.gain ?? 1
        }
        if Thread.isMainThread {
            apply()
        } else {
            DispatchQueue.main.async(execute: apply)
        }
    }

    func play(_ payload: Data) {
        guard payload.count >= 8 else { return }
        let rate = readUInt32(payload, 0)
        let channels = readUInt16(payload, 4)
        let bits = readUInt16(payload, 6)
        guard bits == 16, rate >= 8000, rate <= 192_000, channels == 1 || channels == 2 else { return }
        let pcm = payload.subdata(in: payload.index(payload.startIndex, offsetBy: 8)..<payload.endIndex)
        guard !pcm.isEmpty else { return }
        DispatchQueue.main.async { [weak self] in
            self?.schedule(pcm, rate: Double(rate), channels: AVAudioChannelCount(channels))
        }
    }

    private func schedule(_ pcm: Data, rate: Double, channels: AVAudioChannelCount) {
        if format?.sampleRate != rate || format?.channelCount != channels {
            if started {
                player.stop()
                engine.stop()
                started = false
            }
            guard let format = AVAudioFormat(standardFormatWithSampleRate: rate, channels: channels) else { return }
            self.format = nil
            if !attached {
                engine.attach(player)
                attached = true
            } else {
                engine.disconnectNodeOutput(player)
            }
            guard MirrorConnectPlayer(engine, player, format) else { return }
            do {
                try engine.start()
                player.play()
                player.volume = gain
                started = true
                self.format = format
            } catch {
                return
            }
        }
        guard let format = format, started else { return }
        let channelCount = Int(channels)
        let bytesPerFrame = channelCount * MemoryLayout<Int16>.size
        let frames = pcm.count / bytesPerFrame
        guard frames > 0, let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frames)) else { return }
        buffer.frameLength = AVAudioFrameCount(frames)
        guard let channelData = buffer.floatChannelData else { return }
        var samples = [Int16](repeating: 0, count: frames * channelCount)
        samples.withUnsafeMutableBytes { destination in
            pcm.withUnsafeBytes { source in
                guard let from = source.baseAddress, let to = destination.baseAddress else { return }
                memcpy(to, from, frames * bytesPerFrame)
            }
        }
        for frame in 0..<frames {
            for channel in 0..<channelCount {
                channelData[channel][frame] = Float(samples[frame * channelCount + channel]) / 32768
            }
        }
        player.scheduleBuffer(buffer)
    }

    private func readUInt32(_ data: Data, _ offset: Int) -> UInt32 {
        let start = data.index(data.startIndex, offsetBy: offset)
        var value: UInt32 = 0
        withUnsafeMutableBytes(of: &value) { dest in
            data.copyBytes(to: dest, from: start..<data.index(start, offsetBy: 4))
        }
        return UInt32(bigEndian: value)
    }

    private func readUInt16(_ data: Data, _ offset: Int) -> UInt16 {
        let start = data.index(data.startIndex, offsetBy: offset)
        var value: UInt16 = 0
        withUnsafeMutableBytes(of: &value) { dest in
            data.copyBytes(to: dest, from: start..<data.index(start, offsetBy: 2))
        }
        return UInt16(bigEndian: value)
    }
}
