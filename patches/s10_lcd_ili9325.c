/*
 * s10_lcd_ili9325.c - Universal ILI9325/ILI9328/ILI9341 LCD driver for AirSense 10
 *
 * Calls original ILI9341 board init first, then detects controller via ID read.
 * ILI9325/9328: overrides FlexColor vtable + runs ILI9325 power-on.
 * ILI9341: returns immediately
 */

#define STATIC  static __attribute__((section(".text.x.nonmain")))
#define LCD_DATA_REG  (*(volatile unsigned short *)0x64000002)

typedef unsigned short    uint16;
typedef unsigned char     uint8;

extern void lcd_write_cmd(uint16 index);
extern void lcd_write_data(uint16 value);
extern void lcd_delay_ms(unsigned int ms);
extern void original_board_init(void);
extern void *lcd_get_device(int layer);

STATIC void ili_write_reg(uint16 reg, uint16 val)
{
    lcd_write_cmd(reg);
    lcd_write_data(val);
}

STATIC uint16 ili_read_data(void)
{
    return LCD_DATA_REG;
}

// Read controller ID register (reg 0x00).
// ILI9325 returns 0x9325, ILI9328 returns 0x9328, ILI9341 returns 0x0000.
static inline uint16 read_lcd_id(void)
{
    lcd_write_cmd(0x0000);
    return ili_read_data();
}

// Detect ILI9325/9328 with retries for cold boot stability.
// ILI9325 may need time after power-on before ID register is readable.
STATIC int is_ili932x(void)
{
    int tries;
    for (tries = 0; tries < 3; tries++) {
        uint16 id = read_lcd_id();
        if (id == 0x9325 || id == 0x9328)
            return 1;
        if (tries < 2)
            lcd_delay_ms(1);
    }
    return 0;
}


// FlexColor vtable callbacks for ILI9325/9328

static const uint8 orient_bits[8] = {
    0x30, 0x00, 0x20, 0x10,
    0x38, 0x08, 0x28, 0x18,
};

STATIC void ili9325_set_window(void *ctx, int x0, int y0, int x1, int y1)
{
    int *p = (int *)ctx;
    int xoff = p[0x2C/4];
    int yoff = p[0x30/4];

    ili_write_reg(0x50, (uint16)(xoff + x0));
    ili_write_reg(0x51, (uint16)(xoff + x1));
    ili_write_reg(0x52, (uint16)(yoff + y0));
    ili_write_reg(0x53, (uint16)(yoff + y1));
    ili_write_reg(0x20, (uint16)(xoff + x0));
    ili_write_reg(0x21, (uint16)(yoff + y0));
    lcd_write_cmd(0x22);
}

STATIC void ili9325_set_cursor(void *ctx, int x, int y)
{
    int *p = (int *)ctx;
    int xoff = p[0x2C/4];
    int yoff = p[0x30/4];

    ili_write_reg(0x20, (uint16)(xoff + x));
    ili_write_reg(0x21, (uint16)(yoff + y));
    lcd_write_cmd(0x22);
}

STATIC void ili9325_set_orient(void *ctx)
{
    uint16 flags = *(uint16 *)((uint8 *)ctx + 0x24);
    uint16 entry = orient_bits[flags & 7]; // BGR=0 for emWin RGB565
    lcd_write_cmd(0x03);
    lcd_write_data(entry);
}

STATIC uint16 ili9325_read_pixel(void *ctx)
{
    lcd_write_cmd(0x22);
    (void)ili_read_data();
    return ili_read_data();
}

STATIC void ili9325_read_setup(void *ctx, int x0, int y0, int x1, int y1)
{
    ili9325_set_window(ctx, x0, y0, x1, y1);
}


// ILI9325 power-on sequence
STATIC void ili9325_power_on(void)
{
    ili_write_reg(0x01, 0x0000); // SS=0 (flip horizontal scan for 180 degrees)
    ili_write_reg(0x02, 0x0700);
    ili_write_reg(0x03, 0x0030); // BGR=0 (emWin RGB565), ID1=1, ID0=1
    ili_write_reg(0x04, 0x0000);
    ili_write_reg(0x08, 0x0207);
    ili_write_reg(0x09, 0x0000);
    ili_write_reg(0x0A, 0x0000);
    ili_write_reg(0x0C, 0x0000);
    ili_write_reg(0x0D, 0x0000);
    ili_write_reg(0x0F, 0x0000);

    ili_write_reg(0x10, 0x0000);
    ili_write_reg(0x11, 0x0007);
    ili_write_reg(0x12, 0x0000);
    ili_write_reg(0x13, 0x0000);
    lcd_delay_ms(50);

    ili_write_reg(0x10, 0x1490);
    ili_write_reg(0x11, 0x0227);
    lcd_delay_ms(80);
    ili_write_reg(0x12, 0x001C);
    lcd_delay_ms(50);
    ili_write_reg(0x13, 0x1A00);
    ili_write_reg(0x29, 0x0025);
    ili_write_reg(0x2B, 0x000C);
    lcd_delay_ms(50);

    ili_write_reg(0x50, 0x0000);
    ili_write_reg(0x51, 0x00EF);
    ili_write_reg(0x52, 0x0000);
    ili_write_reg(0x53, 0x013F);

    ili_write_reg(0x60, 0x2700); // GS=0 (flip vertical scan for 180°)
    ili_write_reg(0x61, 0x0001);
    ili_write_reg(0x6A, 0x0000);

    ili_write_reg(0x80, 0x0000);
    ili_write_reg(0x81, 0x0000);
    ili_write_reg(0x82, 0x0000);
    ili_write_reg(0x83, 0x0000);
    ili_write_reg(0x84, 0x0000);
    ili_write_reg(0x85, 0x0000);

    ili_write_reg(0x90, 0x0010);
    ili_write_reg(0x92, 0x0600);
    ili_write_reg(0x93, 0x0003);
    ili_write_reg(0x95, 0x0110);
    ili_write_reg(0x97, 0x0000);
    ili_write_reg(0x98, 0x0000);

    ili_write_reg(0x30, 0x0000);
    ili_write_reg(0x31, 0x0506);
    ili_write_reg(0x32, 0x0104);
    ili_write_reg(0x35, 0x0207);
    ili_write_reg(0x36, 0x000F);
    ili_write_reg(0x37, 0x0306);
    ili_write_reg(0x38, 0x0102);
    ili_write_reg(0x39, 0x0707);
    ili_write_reg(0x3C, 0x0702);
    ili_write_reg(0x3D, 0x1604);

    ili_write_reg(0x07, 0x0133);
    lcd_delay_ms(50);

    // Clear GRAM - ILI9325 has random content on cold power-up
    ili_write_reg(0x20, 0x0000);
    ili_write_reg(0x21, 0x0000);
    lcd_write_cmd(0x22);
    {
        int i;
        for (i = 0; i < 320 * 240; i++)
            LCD_DATA_REG = 0x0000;
    }
}


/*
 * Entry point. Replaces BL to ILI9341 board init at 0x0807BD28.
 * Called from display control function after hardware RESET.
 */
void lcd_board_init(void)
{
    original_board_init();

    if (!is_ili932x())
        return;

    // Override vtable with ILI9325 callbacks
    void *driver = lcd_get_device(0);
    void *ctx = *(void **)((uint8 *)driver + 8);

    *(void **)((uint8 *)ctx + 0x9C) = (void *)ili9325_set_window;
    *(void **)((uint8 *)ctx + 0xA0) = (void *)ili9325_set_cursor;
    *(void **)((uint8 *)ctx + 0xA4) = (void *)ili9325_set_orient;
    *(void **)((uint8 *)ctx + 0xAC) = (void *)ili9325_read_pixel;
    *(void **)((uint8 *)ctx + 0xBC) = (void *)ili9325_read_setup;

    *(uint16 *)((uint8 *)ctx + 0x26) &= ~0x0003;

    ili9325_power_on();
}
