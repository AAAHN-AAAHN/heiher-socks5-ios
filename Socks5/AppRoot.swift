import SwiftUI

@MainActor
struct AppRoot: View {
    @State private var selectedTab = "server"

    var body: some View {
        TabView(selection: $selectedTab) {
            TrafficStatisticsView(isVisible: selectedTab == "statistics")
                .tabItem { Label("Statistics", systemImage: "chart.bar") }
                .tag("statistics")
            ScrollView { ContentView() }
                .tabItem { Label("Server", systemImage: "network") }
                .tag("server")
        }
    }
}
