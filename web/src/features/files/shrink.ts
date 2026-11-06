/**
 * Make a phone photo smaller before it is uploaded (site diary): the longest
 * side at most 1600 px, as JPEG at 80 %. A 4 MB camera photo becomes about
 * 300 KB, so uploads are quick on site and storage stays small. When the
 * browser cannot (or the photo is already small) the file is kept as it is.
 */
export const MAX_SIDE = 1600;

export async function shrinkPhoto(file: File, maxSide = MAX_SIDE): Promise<File> {
  if (!file.type.startsWith("image/") || typeof createImageBitmap !== "function") return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    if (scale === 1 && file.type === "image/jpeg" && file.size < 1_000_000) {
      bitmap.close();
      return file;
    }
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const context = canvas.getContext("2d");
    if (!context) return file;
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob(resolve, "image/jpeg", 0.8);
    });
    if (!blob || blob.size >= file.size) return file;
    const name = file.name.replace(/\.[^.]+$/, "") + ".jpg";
    return new File([blob], name, { type: "image/jpeg" });
  } catch {
    return file; // an image the browser cannot read: upload it as it is
  }
}
