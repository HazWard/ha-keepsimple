from bleak import BleakClient
import asyncio
import sys

from protocol import READ_UUID, SERVICE_UUID, WRITE_UUID


async def scan_device(mac):
    async with BleakClient(mac) as client:
        print("Connected:", client.is_connected)
        for service in client.services:
            marker = " <== KeepSmile service" if service.uuid == SERVICE_UUID else ""
            print(f"Service: {service.uuid}{marker}")
            for char in service.characteristics:
                marker = ""
                if char.uuid == WRITE_UUID:
                    marker = " <== write"
                elif char.uuid == READ_UUID:
                    marker = " <== read/static data"
                print(f"  Characteristic: {char.uuid} - Properties: {char.properties}{marker}")


mac = sys.argv[1] if len(sys.argv) > 1 else "30:58:95:04:56:f9"
asyncio.run(scan_device(mac))
