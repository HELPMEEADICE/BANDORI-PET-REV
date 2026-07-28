import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const DBUS_PATH = '/io/github/bandoripet/PetWayland1';
const DBUS_INTERFACE = 'io.github.bandoripet.PetWayland1';
const APP_ID = 'io.github.bandoripet.BandoriPet';
const MARKER = /\[bandoripet:(p\d+):([0-9a-f]+):([0-9a-f]+):([a-z_]+)\]/;

const INTROSPECTION = `
<node>
  <interface name="${DBUS_INTERFACE}">
    <method name="PushPointer">
      <arg type="d" direction="in"/>
      <arg type="d" direction="in"/>
      <arg type="i" direction="in"/>
      <arg type="i" direction="in"/>
      <arg type="s" direction="in"/>
      <arg type="b" direction="out"/>
    </method>
    <method name="GeometryApplied">
      <arg type="s" direction="in"/>
      <arg type="s" direction="in"/>
      <arg type="i" direction="in"/>
      <arg type="i" direction="in"/>
      <arg type="i" direction="in"/>
      <arg type="i" direction="in"/>
      <arg type="s" direction="in"/>
      <arg type="b" direction="out"/>
    </method>
    <method name="CompanionReady">
      <arg type="s" direction="in"/>
      <arg type="s" direction="in"/>
      <arg type="b" direction="out"/>
    </method>
    <method name="CompanionGone">
      <arg type="s" direction="in"/>
      <arg type="b" direction="out"/>
    </method>
    <signal name="SurfaceUpsert">
      <arg type="s"/><arg type="s"/><arg type="s"/>
      <arg type="i"/><arg type="i"/><arg type="i"/><arg type="i"/>
      <arg type="s"/><arg type="s"/>
    </signal>
    <signal name="SurfaceRemoved"><arg type="s"/><arg type="s"/></signal>
    <signal name="SurfaceCommand">
      <arg type="s"/><arg type="s"/><arg type="s"/><arg type="s"/>
    </signal>
  </interface>
</node>`;

const PetProxy = Gio.DBusProxy.makeProxyWrapper(INTROSPECTION);

export default class BandoriPetWaylandExtension extends Extension {
    enable() {
        this._windows = new Map();
        this._proxies = new Map();
        this._peerTokens = new Map();
        this._signals = [];
        this._lastPointerAt = 0;

        this._signals.push([
            global.display,
            global.display.connect('window-created', (_display, window) => this._trackWindow(window)),
        ]);
        this._signals.push([
            global.stage,
            global.stage.connect('captured-event', (_stage, event) => this._capturedEvent(event)),
        ]);
        this._signals.push([
            Main.sessionMode,
            Main.sessionMode.connect('updated', () => this._syncLockState()),
        ]);
        for (const actor of global.get_window_actors())
            this._trackWindow(actor.metaWindow);
    }

    disable() {
        for (const [object, id] of this._signals)
            object.disconnect(id);
        this._signals = [];
        for (const [service, proxy] of this._proxies) {
            const token = this._peerTokens.get(service);
            if (token)
                proxy.CompanionGoneRemote(token);
        }
        for (const record of this._windows.values())
            this._restoreWindow(record);
        this._windows.clear();
        this._proxies.clear();
        this._peerTokens.clear();
    }

    _trackWindow(window) {
        const match = MARKER.exec(String(window.get_title() || ''));
        if (!match)
            return;
        const markerPid = Number(match[1].slice(1));
        const gtkApplicationId = String(window.get_gtk_application_id?.() || '');
        const wmClass = String(window.get_wm_class?.() || '');
        if (
            Number(window.get_pid()) !== markerPid ||
            ![gtkApplicationId, wmClass].some(value => value.toLowerCase() === APP_ID.toLowerCase())
        )
            return;
        const service = `io.github.bandoripet.PetWayland.${match[1]}`;
        const frame = window.get_frame_rect();
        const record = {
            window,
            service,
            token: match[2],
            surfaceId: match[3],
            role: match[4],
            originalParent: null,
            originalAbove: window.is_above(),
            originalSticky: window.is_on_all_workspaces(),
            originalFrame: [frame.x, frame.y, frame.width, frame.height],
            overlay: false,
        };
        this._windows.set(record.surfaceId, record);
        window.make_above();
        window.stick();
        this._ensureProxy(record);
        this._signals.push([
            window,
            window.connect('unmanaged', () => {
                this._restoreWindow(record);
                this._windows.delete(record.surfaceId);
            }),
        ]);
    }

    _ensureProxy(record) {
        let proxy = this._proxies.get(record.service);
        if (proxy) {
            proxy.CompanionReadyRemote('gnome-shell', record.token);
            return;
        }
        proxy = new PetProxy(
            Gio.DBus.session,
            record.service,
            DBUS_PATH,
            readyProxy => {
                readyProxy.CompanionReadyRemote('gnome-shell', record.token);
            }
        );
        proxy.connectSignal('SurfaceUpsert', (_proxy, _sender, values) => {
            this._surfaceUpsert(values);
        });
        proxy.connectSignal('SurfaceRemoved', (_proxy, _sender, values) => {
            const [surfaceId, token] = values;
            const current = this._windows.get(surfaceId);
            if (current && current.token === token) {
                this._restoreWindow(current);
                this._windows.delete(surfaceId);
            }
        });
        proxy.connectSignal('SurfaceCommand', (_proxy, _sender, values) => {
            const [surfaceId, command, payload, token] = values;
            const current = this._windows.get(surfaceId);
            if (!current || current.token !== token)
                return;
            this._applyCommand(current, command, payload);
        });
        this._proxies.set(record.service, proxy);
        this._peerTokens.set(record.service, record.token);
    }

    _surfaceUpsert(values) {
        const [surfaceId, role, output, x, y, width, height, stackMode, token] = values;
        const record = this._windows.get(surfaceId);
        if (!record || record.token !== token)
            return;
        record.role = role;
        record.output = output;
        record.stackMode = stackMode;
        record.window.move_resize_frame(false, x, y, width, height);
        record.window.make_above();
        record.window.stick();
        this._setOverlay(record, stackMode === 'game_overlay' && !Main.sessionMode.isLocked);
        const proxy = this._proxies.get(record.service);
        if (proxy)
            proxy.GeometryAppliedRemote(surfaceId, output, x, y, width, height, token);
    }

    _setOverlay(record, enabled) {
        const actor = record.window.get_compositor_private();
        if (!actor)
            return;
        if (enabled && !record.overlay) {
            record.originalParent = actor.get_parent();
            if (record.originalParent)
                record.originalParent.remove_child(actor);
            global.top_window_group.add_child(actor);
            record.overlay = true;
        } else if (!enabled && record.overlay) {
            global.top_window_group.remove_child(actor);
            if (record.originalParent)
                record.originalParent.add_child(actor);
            record.originalParent = null;
            record.overlay = false;
        }
    }

    _applyCommand(record, command, payload) {
        if (command === 'activate')
            Main.activateWindow(record.window);
        else if (command === 'raise')
            record.window.make_above();
        else if (command === 'release_overlay')
            this._setOverlay(record, false);
    }

    _restoreWindow(record) {
        this._setOverlay(record, false);
        try {
            if (!record.originalAbove)
                record.window.unmake_above();
            if (!record.originalSticky)
                record.window.unstick();
            const [x, y, width, height] = record.originalFrame;
            record.window.move_resize_frame(false, x, y, width, height);
        } catch (_error) {
            // The window may already be unmanaged.
        }
    }

    _syncLockState() {
        for (const record of this._windows.values())
            this._setOverlay(record, record.stackMode === 'game_overlay' && !Main.sessionMode.isLocked);
    }

    _capturedEvent(event) {
        if (event.type() !== Clutter.EventType.MOTION)
            return Clutter.EVENT_PROPAGATE;
        const now = GLib.get_monotonic_time();
        if (now - this._lastPointerAt < 16000)
            return Clutter.EVENT_PROPAGATE;
        this._lastPointerAt = now;
        const [x, y, modifiers] = global.get_pointer();
        for (const [service, proxy] of this._proxies) {
            const token = this._peerTokens.get(service);
            if (proxy)
                proxy.PushPointerRemote(
                    x,
                    y,
                    modifiers,
                    Math.floor(now / 1000) % 2147483647,
                    token
                );
        }
        return Clutter.EVENT_PROPAGATE;
    }
}
