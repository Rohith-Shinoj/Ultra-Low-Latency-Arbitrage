#!/bin/bash
# scripts/setup_veth.sh

set -e

echo "Cleaning up any existing veth pairs..."
sudo ip link delete veth0 2>/dev/null || true

echo "Creating veth pair: veth0 <--> veth1"
sudo ip link add veth0 type veth peer name veth1

echo "Assigning IPs..."
sudo ip addr add 10.10.10.1/24 dev veth0
sudo ip addr add 10.10.10.2/24 dev veth1

echo "Bringing up interfaces..."
sudo ip link set veth0 up
sudo ip link set veth1 up

echo "Adding multicast routes..."
# Route multicast traffic in the 239.1.1.0/24 range over these interfaces
sudo ip route add 239.1.1.0/24 dev veth0 || true
sudo ip route add 239.1.1.0/24 dev veth1 || true

echo "Verification:"
ip -4 addr show veth0
ip -4 addr show veth1
ip route | grep 239.1.1.0

echo "veth setup complete. Multicast routing enabled."
