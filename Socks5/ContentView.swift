//
//  ContentView.swift
//  Socks5
//

import SwiftUI

struct ContentView: View {
    @Binding var configuration: ServerSettings
    @ObservedObject var server: ServerController
    let desiredRunning: Bool
    let setRunning: (Bool) -> Void

    var body: some View {
        VStack {
            Text("Workers:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("", text: $configuration.workers)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .keyboardType(.numberPad)
                .frame(maxWidth: .infinity, alignment: .leading)
                .disabled(server.isRunning)

            Text("Listen Address:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("", text: $configuration.listenAddress)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(server.isRunning)

            Text("Listen Port:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("", text: $configuration.listenPort)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .keyboardType(.numberPad)
                .frame(maxWidth: .infinity)
                .disabled(server.isRunning)

            Text("UDP Listen Address:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("Optional", text: $configuration.udpListenAddress)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(server.isRunning)

            Text("UDP Listen Port:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("", text: $configuration.udpListenPort)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .keyboardType(.numberPad)
                .frame(maxWidth: .infinity)
                .disabled(server.isRunning)

            Text("Bind IPv4 Address:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("", text: $configuration.bindIPv4Address)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(server.isRunning)

            Text("Bind IPv6 Address:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("", text: $configuration.bindIPv6Address)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(server.isRunning)

            Text("Bind Interface:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("Optional", text: $configuration.bindInterface)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(server.isRunning)

            Text("Auth Username:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("Optional", text: $configuration.authUsername)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(server.isRunning)

            Text("Auth Password:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            SecureField("Optional", text: $configuration.authPassword)
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(server.isRunning)

            Toggle(isOn: $configuration.listenIPv6Only) {
                Text("Listen IPv6 only")
                    .font(.headline)
            }
            .toggleStyle(SwitchToggleStyle())
            .frame(maxWidth: .infinity)
            .disabled(server.isRunning)

            HStack {
                Button(action: {
                    setRunning(true)
                    server.apply(configuration, running: true, retry: true)
                }) {
                    Text("Start")
                    .font(.headline)
                    .padding()
                    .cornerRadius(10)
                }
                .disabled(server.isRunning)
                Button(action: {
                    setRunning(false)
                    server.apply(configuration, running: false)
                }) {
                    Text("Stop")
                    .font(.headline)
                    .padding()
                    .cornerRadius(10)
                }
                .disabled(!server.isRunning && !desiredRunning)
            }

            Text(server.status).font(.footnote)
            Spacer()
        }
        .padding()
    }
}

#Preview {
    ContentView(configuration: .constant(ServerSettings()), server: ServerController(),
                desiredRunning: false, setRunning: { _ in })
}
