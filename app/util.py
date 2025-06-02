# app/util.py

def to_alphanumeric_bed_id(number, beds_per_row=9):
    """Converts an integer bed number to alphanumeric format like A-1.

    Args:
        number (int): The integer bed number (e.g., 1, 2, 10).
        beds_per_row (int): Number of beds in a single row (e.g., A-1 to A-9 means 9 beds).

    Returns:
        str: The alphanumeric bed ID (e.g., "A-1", "B-1").
             Returns the original number as a string if the input is invalid.
    """
    if not isinstance(number, int) or number < 1:
        return str(number)  # Return as string for invalid inputs

    # Calculate row index (0 for 'A', 1 for 'B', etc.)
    row_index = (number - 1) // beds_per_row
    # Calculate column index (1-based within the row)
    col_index = (number - 1) % beds_per_row + 1

    # Convert row index to a letter
    row_letter = chr(ord('A') + row_index)

    return f"{row_letter}-{col_index}"

