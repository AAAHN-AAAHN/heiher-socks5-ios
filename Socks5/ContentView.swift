//
//  ContentView.swift
//  Socks5
//

import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var settings: SettingsStore
    @EnvironmentObject private var server: ServerController

    var body: some View {
        VStack {
            Text("Workers:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("", text: settings.binding(\.server.workers))
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
            TextField("", text: settings.binding(\.server.listenAddress))
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(server.isRunning)

            Text("Listen Port:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("", text: settings.binding(\.server.listenPort))
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
            TextField("Optional", text: settings.binding(\.server.udpListenAddress))
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(server.isRunning)

            Text("UDP Listen Port:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("", text: settings.binding(\.server.udpListenPort))
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
            TextField("", text: settings.binding(\.server.bindIPv4Address))
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(server.isRunning)

            Text("Bind IPv6 Address:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("", text: settings.binding(\.server.bindIPv6Address))
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(server.isRunning)

            Text("Bind Interface:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("Optional", text: settings.binding(\.server.bindInterface))
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(server.isRunning)

            Text("Auth Username:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("Optional", text: settings.binding(\.server.authUsername))
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(server.isRunning)

            Text("Auth Password:")
                .font(.headline)
                .padding(.bottom, 0)
                .frame(maxWidth: .infinity, alignment: .leading)
            SecureField("Optional", text: settings.binding(\.server.authPassword))
                .padding(.top, 0)
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .autocapitalization(.none)
                .frame(maxWidth: .infinity)
                .disabled(server.isRunning)

            Toggle(isOn: settings.binding(\.server.listenIPv6Only)) {
                Text("Listen IPv6 only")
                    .font(.headline)
            }
            .toggleStyle(SwitchToggleStyle())
            .frame(maxWidth: .infinity)
            .disabled(server.isRunning)

            HStack {
                Button(action: {
                    settings.set(\.serverRunning, true)
                    server.apply(settings.value)
                }) {
                    Text("Start")
                    .font(.headline)
                    .padding()
                    .cornerRadius(10)
                }
                .disabled(server.isRunning)
                Button(action: {
                    settings.set(\.serverRunning, false)
                    server.apply(settings.value)
                }) {
                    Text("Stop")
                    .font(.headline)
                    .padding()
                    .cornerRadius(10)
                }
                .disabled(!server.isRunning && !settings.value.serverRunning)
            }

            Text(server.status).font(.footnote)
            if let error = settings.errorMessage { Text(error).font(.footnote) }
            Spacer()
        }
        .padding()
    }
}

#Preview {
    ContentView().environmentObject(SettingsStore()).environmentObject(ServerController())
}
