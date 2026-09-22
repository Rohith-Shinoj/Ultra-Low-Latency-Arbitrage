#pragma once

#include <string>
#include <vector>
#include <iostream>
#include <fstream>
#include <filesystem>
#include <cstdlib>
#include <cstring>
#include <unistd.h>
#include <sys/socket.h>
#include <dlfcn.h>

namespace ull {

struct SolarflareDeviceInfo {
    std::string interface_name;
    std::string vendor_id;
    std::string device_id;
    bool is_solarflare = false;
};

struct SolarflareScanResult {
    bool onload_driver_active = false;      // /dev/onload or /proc/driver/onload present
    bool onload_env_active = false;         // running under onload wrapper
    bool onload_symbol_active = false;      // onload_is_present() symbol detected
    bool solarflare_nic_found = false;      // PCIe vendor 0x1924 (Solarflare) or 0x10ee (AMD/Xilinx)
    std::vector<SolarflareDeviceInfo> devices;
    std::string active_interface;
    std::string mode_description;

    bool is_accelerated() const {
        return onload_driver_active || onload_env_active || onload_symbol_active || solarflare_nic_found;
    }
};

class SolarflareManager {
public:
    static SolarflareScanResult scan_hardware() {
        SolarflareScanResult res;

        std::cout << "\n═══════════════════════════════════════════════════════════════════════════════\n";
        std::cout << "          HARDWARE SCAN: SOLARFLARE OPENONLOAD / EF_VI KERNEL BYPASS           \n";
        std::cout << "═══════════════════════════════════════════════════════════════════════════════\n";

        // 1. Check Onload Process Environment Variables
        if (std::getenv("ONLOAD_ACTIVE") != nullptr || std::getenv("ONLOAD_EXT_LIB") != nullptr) {
            res.onload_env_active = true;
            std::cout << "  • Onload Environment: [DETECTED] Process running within Onload namespace\n";
        } else {
            std::cout << "  • Onload Environment: [NOT DETECTED] Process running in standard namespace\n";
        }

        // 2. Check Onload Kernel Character Devices & Procfs
        if (access("/dev/onload", F_OK) == 0 || access("/dev/onload_epoll", F_OK) == 0) {
            res.onload_driver_active = true;
            std::cout << "  • Driver Character Device (/dev/onload): [PRESENT] Hardware acceleration ready\n";
        } else if (access("/proc/driver/onload", F_OK) == 0) {
            res.onload_driver_active = true;
            std::cout << "  • Driver Procfs (/proc/driver/onload): [PRESENT] Onload kernel module loaded\n";
        } else {
            std::cout << "  • Driver Device (/dev/onload, /proc/driver/onload): [NOT FOUND]\n";
        }

        // 3. Check for dynamic symbols from libonload.so
        typedef int (*onload_is_present_fn)();
        onload_is_present_fn fn = (onload_is_present_fn)dlsym(RTLD_DEFAULT, "onload_is_present");
        if (fn != nullptr && fn() == 1) {
            res.onload_symbol_active = true;
            std::cout << "  • Onload User-Space Extensions: [ACTIVE] onload_is_present() == true\n";
        }

        // 4. Scan System PCIe Network Adapters via sysfs
        namespace fs = std::filesystem;
        std::cout << "  • Probing PCIe Devices & Netdevs for Vendor IDs 0x1924 (Solarflare) / 0x10ee (AMD/Xilinx):\n";
        try {
            if (fs::exists("/sys/class/net")) {
                for (const auto& entry : fs::directory_iterator("/sys/class/net")) {
                    std::string ifname = entry.path().filename().string();
                    if (ifname == "lo") continue;

                    std::string vendor_path = entry.path().string() + "/device/vendor";
                    std::string device_path = entry.path().string() + "/device/device";

                    if (fs::exists(vendor_path)) {
                        std::ifstream vf(vendor_path);
                        std::string vendor;
                        if (vf >> vendor) {
                            SolarflareDeviceInfo dev;
                            dev.interface_name = ifname;
                            dev.vendor_id = vendor;

                            if (fs::exists(device_path)) {
                                std::ifstream df(device_path);
                                df >> dev.device_id;
                            }

                            // 0x1924 = Solarflare Communications
                            // 0x10ee = Xilinx / AMD (Alveo / Solarflare X2522 / SFN8522 series)
                            if (vendor == "0x1924" || (vendor == "0x10ee" && dev.device_id.rfind("0x0", 0) == 0)) {
                                dev.is_solarflare = true;
                                res.solarflare_nic_found = true;
                                res.devices.push_back(dev);
                                if (res.active_interface.empty()) {
                                    res.active_interface = ifname;
                                }
                                std::cout << "    ✔ MATCH: Interface " << ifname 
                                          << " | Vendor: " << vendor << " (Solarflare) | Device: " 
                                          << dev.device_id << "\n";
                            } else {
                                std::cout << "    - Interface " << ifname 
                                          << " | Vendor: " << vendor << " (Standard NIC) | Device: " 
                                          << dev.device_id << "\n";
                            }
                        }
                    }
                }
            }
        } catch (...) {
            // Sysfs access guard
        }

        std::cout << "───────────────────────────────────────────────────────────────────────────────\n";
        if (res.is_accelerated()) {
            std::cout << "\033[92m\033[1m[SCAN RESULT] SOLARFLARE HARDWARE / ONLOAD DETECTED!\033[0m\n";
            std::cout << "  • Mode: Solarflare OpenOnload Direct Hardware Kernel Bypass (ef_vi accelerated)\n";
            res.mode_description = "Solarflare OpenOnload (Direct HW Kernel Bypass)";
        } else {
            std::cout << "\033[93m[SCAN RESULT] No Solarflare SFC hardware or Onload driver present on system.\033[0m\n";
            std::cout << "\033[92m\033[1m  • FALLBACK: Linux AF_XDP Zero-Copy Kernel Bypass\033[0m\n";
            res.mode_description = "AF_XDP (Kernel Bypass Fallback - Solarflare Probed)";
        }
        std::cout << "═══════════════════════════════════════════════════════════════════════════════\n\n";

        return res;
    }

    // Configures socket options for ultra-low latency under Solarflare Onload
    static void configure_onload_socket(int fd) {
        // Enable kernel-bypass busy polling on the socket
#ifdef SO_BUSY_POLL
        int busy_poll = 50;
        setsockopt(fd, SOL_SOCKET, SO_BUSY_POLL, &busy_poll, sizeof(busy_poll));
#endif
#ifdef SO_LOW_LATENCY
        int low_latency = 1;
        setsockopt(fd, SOL_SOCKET, SO_LOW_LATENCY, &low_latency, sizeof(low_latency));
#endif
        (void)fd;
    }
};

} // namespace ull
