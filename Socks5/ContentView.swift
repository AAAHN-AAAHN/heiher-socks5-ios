//
//  ContentView.swift
//  Socks5
//

import SwiftUI
import HevSocks5Server

@MainActor
struct ContentView: View {
    var serverChanged: @MainActor (UUID?, Socks5UDPClient.Credentials?, Bool) -> Void = { _, _, _ in }
    @State private var workersText: String = "4"
    @State private var listenAddrText: String = "::"
    @State private var listenPortText: String = "1080"
    @State private var udpListenAddrText: String = ""
    @State private var udpListenPortText: String = "1080"
    @State private var bindIpv4AddrText: String = "0.0.0.0"
    @State private var bindIpv6AddrText: String = "::"
    @State private var bindIfaceText: String = ""
    @State private var authUserText: String = ""
    @State private var authPassText: String = ""
    @State private var listenIpv6OnlyToggle: Bool = false
    @State private var isRunning: Bool = false
    @State private var invocation: UUID?
    @State private var stopping = false

    var body: some View {
        VStack {
            Text("Workers:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("", text: $workersText)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .keyboardType(.numberPad)
                .frame(maxWidth: .infinity, alignment: .leading)
                .disabled(isRunning)

            Text("Listen Address:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("", text: $listenAddrText)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(isRunning)

            Text("Listen Port:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("", text: $listenPortText)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .keyboardType(.numberPad)
                .frame(maxWidth: .infinity)
                .disabled(isRunning)

            Text("UDP Listen Address:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("Optional", text: $udpListenAddrText)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(isRunning)

            Text("UDP Listen Port:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("", text: $udpListenPortText)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .keyboardType(.numberPad)
                .frame(maxWidth: .infinity)
                .disabled(isRunning)

            Text("Bind IPv4 Address:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("", text: $bindIpv4AddrText)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(isRunning)

            Text("Bind IPv6 Address:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("", text: $bindIpv6AddrText)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(isRunning)

            Text("Bind Interface:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("Optional", text: $bindIfaceText)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(isRunning)

            Text("Auth Username:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("Optional", text: $authUserText)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(isRunning)

            Text("Auth Password:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            SecureField("Optional", text: $authPassText)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(isRunning)

            Toggle(isOn: $listenIpv6OnlyToggle) {
                Text("Listen IPv6 only")
                    .font(.headline)
            }
            .toggleStyle(SwitchToggleStyle())
            .frame(maxWidth: .infinity)
            .disabled(isRunning)

            HStack {
                Button(action: {
                    guard invocation == nil else { return }
                    func quote(_ value: String) -> String { value.replacingOccurrences(of: "'", with: "''") }
                    let conf = """
                            main:
                              workers: \(workersText)
                              port: \(listenPortText)
                              listen-address: '\(quote(listenAddrText))'
                              udp-port: \(udpListenPortText)
                              udp-listen-address: '\(quote(udpListenAddrText))'
                              listen-ipv6-only: \(listenIpv6OnlyToggle)
                              bind-address-v4: '\(quote(bindIpv4AddrText))'
                              bind-address-v6: '\(quote(bindIpv6AddrText))'
                              bind-interface: '\(quote(bindIfaceText))'
                            auth:
                              username: '\(quote(authUserText))'
                              password: '\(quote(authPassText))'
                            """
                    let credentials: Socks5UDPClient.Credentials? = authUserText.isEmpty ? nil :
                        .init(username: authUserText, password: authPassText)
                    let preferIPv4 = Socks5UDPClient.Address(host: udpListenAddrText, port: 0)?.family == AF_INET
                    let id = UUID()
                    // Clear only idle cancellation, before this invocation accepts Stop.
                    hev_socks5_server_prepare()
                    invocation = id
                    isRunning = true
                    stopping = false
                    DispatchQueue.global(qos: .utility).async {
                        let _ = hev_socks5_server_main_from_str(conf, UInt32(conf.utf8.count))
                        Task { @MainActor in
                            guard invocation == id else { return }
                            invocation = nil
                            isRunning = false
                            stopping = false
                            serverChanged(nil, nil, false)
                        }
                    }
                    serverChanged(id, credentials, preferIPv4)
                }) {
                    Text("Start")
                    .font(.headline)
                    .padding()
                    .cornerRadius(10)
                }
                .disabled(isRunning)
                Button(action: {
                    guard !stopping else { return }
                    stopping = true
                    serverChanged(nil, nil, false)
                    hev_socks5_server_quit()
                }) {
                    Text("Stop")
                    .font(.headline)
                    .padding()
                    .cornerRadius(10)
                }
                .disabled(!isRunning || stopping)
            }

            Spacer()
        }
        .padding()
    }
}

#Preview {
    ContentView()
}
