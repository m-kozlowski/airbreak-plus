# Backlight Adaptation

The backlight patch continuously maps the filtered ambient-light reading to LCD
and button brightness while the display is in its steady on state. Stock
firmware remains responsible for wake, timeout, dim, off, and other transition
states.

## Inputs

| Input | Function |
|-------|----------|
| filtered ambient reading (ASF) | current ambient-light level |
| Ambient Low | start of the linear brightness range |
| Ambient High | end of the linear brightness range |
| LCD / Low and LCD / High | LCD brightness endpoints |
| Buttons / Low and Buttons / High | button brightness endpoints |

## Brightness mapping

| Ambient reading | LCD target | Button target |
|-----------------|------------|---------------|
| ASF at or below Ambient Low | LCD / Low | Buttons / Low |
| between Ambient Low and Ambient High | linear interpolation between LCD endpoints | linear interpolation between button endpoints |
| ASF at or above Ambient High | LCD / High | Buttons / High |

The patch applies a one-level deadband to intermediate LCD target changes and
advances brightness gradually. Exact low and high endpoints remain reachable.

When stock firmware enters a non-steady transition, the patch calls the stock
state machine. Afterward, it briefly reasserts the ambient-selected levels so
the end of the stock transition cannot leave stale brightness values.

## Settings

| Setting | UART | Range | Default | Menu | Visible modes | Function | Without `custom_settings` |
|---------|------|-------|---------|------|---------------|----------|---------------------------|
| Ambient Low | `ATH` | 0 to 4090, step 5 | 590 | Configuration | All | Sets the ambient reading where brightness leaves its low endpoints | Uses ATH; patched default 590 |
| Ambient High | `RCF` | 0 to 4090, step 10 | 3070 | Configuration | All | Sets the ambient reading where brightness reaches its high endpoints; zero restores stock handling | Fixed `0xC00` threshold |
| LCD / Low | `LLL` | 0 to 100, step 1 | 60 | Configuration | All | Sets LCD brightness at and below Ambient Low | Uses LLL |
| LCD / High | `LLH` | 0 to 100, step 1 | 100 | Configuration | All | Sets LCD brightness at and above Ambient High | Uses LLH |
| Buttons / Low | `LBL` | 0 to 100, step 1 | 32 | Configuration | All | Sets button brightness at and below Ambient Low | Uses LBL; patched default 32 |
| Buttons / High | `LBH` | 0 to 100, step 1 | 80 | Configuration | All | Sets button brightness at and above Ambient High | Uses LBH; patched default 80 |

LCD and Buttons are headings within the generated Configuration group.
Firmware variable assignments and persistence are listed in the
[custom settings registry](../../custom_settings.md#assignments).

Ambient High should normally be greater than Ambient Low. If it is equal or
lower, the interpolated range collapses and brightness changes directly from
the low endpoint to the high endpoint after Ambient Low.

Setting Ambient High to zero restores stock backlight behavior. The patched
default values and ambient-light averaging remain in effect.

## Related settings

Changing the LCD or button controls changes the brightness endpoints but not
the ambient thresholds. Changing Ambient Low or Ambient High changes the sensor
range but not endpoint brightness.

![Backlight target curves](../../images/backlight_adapt_behavior.svg)
