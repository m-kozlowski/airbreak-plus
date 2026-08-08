/* FGBL 1.1.0. */

#define NSTUB(addr, name) \
    .global name; \
    .type name, %function; \
    .thumb_set name, addr

#define NDATA(addr, name) \
    .global name; \
    .type name, %object; \
    name = addr

.text

NSTUB(0x08000940, fgbl_copy_sram_updater_and_jump)
NSTUB(0x08000990, fgbl_jump_to_application)
NSTUB(0x24007DC0, sram_updater_run_staged_upgrade_flow)
NSTUB(0x240071B2, sram_nor_read_job_submit_and_copy)
NSTUB(0x2400720E, sram_nor_read_job_transmit)
NSTUB(0x24007314, sram_nor_read_job_get)
NSTUB(0x24007346, sram_writer_wrapper_service)
NSTUB(0x240074B8, sram_flash_writer_init)
NSTUB(0x24007508, sram_flash_writer_queue_overlapping_sectors)
NSTUB(0x24007546, sram_flash_writer_unlock)
NSTUB(0x2400754E, sram_flash_writer_lock)
NSTUB(0x24007556, sram_flash_writer_busy)
NSTUB(0x2400757C, sram_flash_writer_erase_next_sector)
NSTUB(0x240075CC, sram_flash_writer_erase_queue_done)
NSTUB(0x240075DE, sram_flash_writer_program_range)
NSTUB(0x2400762C, sram_flash_writer_flush_partial)
NSTUB(0x2400ECC4, sram_nor_enable_status_write_protection)
NSTUB(0x2400EE68, sram_nor_set_chip_select)
NSTUB(0x2400EE9A, sram_nor_set_write_protect)
NSTUB(0x2400EEB4, sram_nor_spi_reader_singleton)

NDATA(0x08000A40, fgbl_stock_request_magic)
NDATA(0x24026B20, sram_flash_writer_singleton)
NDATA(0x24026FF0, sram_writer_wrapper_singleton)
NDATA(0x2401FFF0, fgbl_service_cookie)
NDATA(0x2401FFF4, fgbl_service_active)
