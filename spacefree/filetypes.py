"""File-type classes used for the space-by-type breakdown and the Media tab."""
from __future__ import annotations

IMAGE = "Images"
AUDIO = "Audio"
VIDEO = "Video"
DOCS = "Documents"
ARCHIVE = "Archives & installers"
DISKIMG = "Disk images & VMs"
CODE = "Code & data"
APPS = "Apps & system"
OTHER = "Other"

_EXT = {
    IMAGE: ".jpg .jpeg .png .gif .bmp .webp .tif .tiff .heic .heif .svg .raw .cr2 .nef .dng .psd .ico",
    AUDIO: ".mp3 .wav .flac .aac .m4a .ogg .wma .opus .aiff .mid",
    VIDEO: ".mp4 .mkv .avi .mov .wmv .flv .webm .m4v .mpg .mpeg .3gp .ts .m2ts",
    DOCS: ".pdf .doc .docx .xls .xlsx .ppt .pptx .txt .md .csv .rtf .odt .epub",
    ARCHIVE: ".zip .rar .7z .tar .gz .bz2 .xz .cab .msi .msix .exe.part",
    DISKIMG: ".iso .img .vhd .vhdx .vmdk .vdi .ova .qcow2 .dmg .wim",
    CODE: ".py .js .ts .tsx .jsx .java .c .cpp .h .cs .go .rs .php .rb .json .xml .html .css .sql .db .sqlite .log",
    APPS: ".exe .dll .sys .dat .bin .lib .pdb .pak .mui .cat",
}
EXT_TYPE: dict[str, str] = {e: t for t, exts in _EXT.items() for e in exts.split()}
# .ts is ambiguous (TypeScript vs video); treat as code
EXT_TYPE[".ts"] = CODE

MEDIA_TYPES = (IMAGE, AUDIO, VIDEO)
ALL_TYPES = (VIDEO, IMAGE, AUDIO, DOCS, ARCHIVE, DISKIMG, CODE, APPS, OTHER)


def type_of(ext: str) -> str:
    return EXT_TYPE.get(ext, OTHER)
