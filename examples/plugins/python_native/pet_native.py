ORIGINAL = None


def activate_native(host):
    global ORIGINAL
    pet = host.window
    ORIGINAL = pet._bring_to_front

    def keep_current_layer(force=False):
        # This private behavior is intentionally unavailable to managed plugins.
        # The example suppresses forced layer changes on an ordinary click.
        if not force:
            return None
        return ORIGINAL(force=False)

    pet._bring_to_front = keep_current_layer
    host.api.log.warning("Native example replaced PetWindow._bring_to_front")


def deactivate_native(reason):
    # Native enable/disable is restart-based, so process teardown restores the class naturally.
    return None
