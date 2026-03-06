import os

# Simulate the full path being passed
directory_name = "C:\\Users\\Babit-PC\\.nami\\skills\\algorithmic-art"
normalized_dir_name = directory_name.rstrip("/\\")
print(f"directory_name: {directory_name!r}")
print(f"normalized_dir_name: {normalized_dir_name!r}")

# The issue might be here - what if os.path.basename was already called
# But then the result contains a full path?
if os.sep in normalized_dir_name or "/" in normalized_dir_name:
    print("Found separator, calling os.path.basename")
    normalized_dir_name = os.path.basename(normalized_dir_name)
    print(f"After basename: {normalized_dir_name!r}")
else:
    print("No separator found")
print(f"Final: {normalized_dir_name!r}")
