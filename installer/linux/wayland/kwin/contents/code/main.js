"use strict";

const DBUS_PATH = "/io/github/bandoripet/PetWayland1";
const DBUS_INTERFACE = "io.github.bandoripet.PetWayland1";
const APP_ID = "io.github.bandoripet.BandoriPet";
const MARKER = /\[bandoripet:(p\d+):([0-9a-f]+):([0-9a-f]+):([a-z_]+)\]/;
const peers = new Map();
let lastSentAt = 0;

function rememberWindow(window) {
    const caption = String(window.caption || "");
    const match = MARKER.exec(caption);
    if (!match)
        return;
    const markerPid = Number(match[1].slice(1));
    const resourceClass = String(window.resourceClass || "");
    if (Number(window.pid) !== markerPid || resourceClass.toLowerCase() !== APP_ID.toLowerCase())
        return;
    const service = `io.github.bandoripet.PetWayland.${match[1]}`;
    let peer = peers.get(service);
    if (!peer) {
        peer = {token: match[2], surfaces: new Set()};
        peers.set(service, peer);
    }
    if (peer.token !== match[2])
        return;
    peer.surfaces.add(match[3]);
    callDBus(
        service,
        DBUS_PATH,
        DBUS_INTERFACE,
        "CompanionReady",
        "kwin-6",
        match[2]
    );
}

function forgetWindow(window) {
    const caption = String(window.caption || "");
    const match = MARKER.exec(caption);
    if (!match)
        return;
    const service = `io.github.bandoripet.PetWayland.${match[1]}`;
    const peer = peers.get(service);
    if (!peer || peer.token !== match[2])
        return;
    peer.surfaces.delete(match[3]);
    if (peer.surfaces.size === 0)
        peers.delete(service);
}

function sendPointer() {
    const now = Date.now();
    if (now - lastSentAt < 16)
        return;
    lastSentAt = now;
    const point = workspace.cursorPos;
    for (const [service, peer] of peers) {
        callDBus(
            service,
            DBUS_PATH,
            DBUS_INTERFACE,
            "PushPointer",
            Number(point.x),
            Number(point.y),
            0,
            now & 0x7fffffff,
            peer.token
        );
    }
}

for (const window of workspace.stackingOrder)
    rememberWindow(window);
workspace.windowAdded.connect(rememberWindow);
workspace.windowRemoved.connect(forgetWindow);
workspace.cursorPosChanged.connect(sendPointer);
