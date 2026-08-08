# Allocate measured payloads into the known code caves for one firmware key.
#
# Code-cave rows:
#   version region storage_start storage_end image_base runtime_base
#
# Payload-size rows:
#   payload size region
#
# The output columns are:
#   payload runtime size runtime_end storage storage_end

function fail(message)
{
	print "generate_payload_layout: " message > "/dev/stderr"
	exit 1
}

function hex_value(text,    i, digit, value)
{
	if (text !~ /^0[xX][0-9a-fA-F]+$/)
		fail("invalid hexadecimal address: " text)

	value = 0
	for (i = 3; i <= length(text); i++) {
		digit = index("0123456789abcdef", tolower(substr(text, i, 1))) - 1
		value = value * 16 + digit
	}
	return value
}

function align4(value)
{
	return int((value + 3) / 4) * 4
}

BEGIN {
	FS = "[[:space:]]+"
	if (version == "")
		fail("version is required")

	print "# payload\truntime\tsize\truntime_end\tstorage\tstorage_end"
}

FNR == NR {
	if ($0 ~ /^[[:space:]]*(#|$)/ || $1 != version)
		next

	if (NF != 6)
		fail("invalid cave row: " $0)
	region = $2
	start = hex_value($3)
	end = hex_value($4)
	image_base = hex_value($5)
	runtime_base = hex_value($6)
	if (region !~ /^[a-zA-Z_][a-zA-Z0-9_]*$/)
		fail("invalid cave region: " region)
	if (start % 4 != 0 || end <= start)
		fail("invalid cave for " version ": " $0)
	if (image_base % 4 != 0 || runtime_base % 4 != 0 || start < image_base)
		fail("invalid cave mapping for " version ": " $0)
	if (cave_count && start < cave_end[cave_count])
		fail("overlapping or unsorted caves for " version)

	cave_count++
	cave_region[cave_count] = region
	cave_start[cave_count] = start
	cave_end[cave_count] = end
	cave_next[cave_count] = start
	cave_image_base[cave_count] = image_base
	cave_runtime_base[cave_count] = runtime_base
	next
}

$0 ~ /^[[:space:]]*(#|$)/ {
	next
}

{
	if (!cave_count)
		fail("no code caves defined for " version)

	if (NF != 3)
		fail("invalid payload size row: " $0)
	payload = $1
	size = $2 + 0
	region = $3
	if (payload !~ /^[a-zA-Z_][a-zA-Z0-9_]*$/ || size <= 0)
		fail("invalid payload size row: " $0)
	if (region !~ /^[a-zA-Z_][a-zA-Z0-9_]*$/)
		fail("invalid payload region: " region)
	if (seen[payload]++)
		fail("duplicate payload: " payload)

	placed = 0
	for (i = 1; i <= cave_count; i++) {
		if (cave_region[i] != region)
			continue
		address = align4(cave_next[i])
		storage_end = address + size
		if (storage_end <= cave_end[i]) {
			cave_next[i] = storage_end
			placed = 1
			break
		}
	}
	if (!placed)
		fail(payload " (" size " bytes) does not fit in " version "/" region " code caves")

	# Mapped regions can store a payload in flash while linking it for the
	# address at which the native firmware copies and executes it.
	runtime = cave_runtime_base[i] + address - cave_image_base[i]
	runtime_end = runtime + size
	printf "%s\t0x%08X\t%d\t0x%08X\t0x%08X\t0x%08X\n", \
		payload, runtime, size, runtime_end, address, storage_end
}

END {
	if (!cave_count)
		fail("no code caves defined for " version)
}
