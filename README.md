# Readme

So, what the heck is this?
This is an image database tool, called "imgdb", slightly similar to unix-like "find". 
You create a config for it, specify which directories and extensions it is supposed to scan, then ask it to scan files, create hashes for them, create image hashes for them and ocr them.
Then you can search images by color and OCRed text

Oh, right. This is completely unsupported. It is a pet/toy project, so "abandon all hope", I mean proceed at your own risk.

# Requirements 

It requires pytesseract, dhash, sql alchemy and numpy. There's no requirements.txt because I wrote this in vscode and not in pycharm with venvs.

# Usage

Running it once should create a config file called `imgdbcfg.json`. The contents should look like this:

```
{
	"tesscmd": "D:\\My\\Program\\files\\Tesseract-OCR\\tesseract.exe",
	"dbpath": "imgdb2.db",
	"paths": [
		"E:/my/picture/folder",
		"E:/my/other/picture/folder"
	],
	"excludePaths": [
	],
	"extensions": [
		".png",
		".tga",
		".jpeg",
		".jpg",
		".bmp"
	]
}
```

Well, that's an example, but basically.. "dbpath" is where you store the database, "tesscmd" is how you run tesseract, "paths' are paths with image directories, "excludePaths" are paths the tool shouldn't check,
extensiosn are extensions it is supposed to monitor.

Once you configured this, you can print help with --help.

This will get you something like this:
```
usage: imgdb.py [-h] [--scan] [--pal] [--killpal] [--killdupes] [--hash]
                [--imghash] [--ocr] [--killocr] [--ocrmask OCRMASK]
                [--lang LANG] [--random] [--findmaincolor FINDMAINCOLOR]
                [--findcolor FINDCOLOR] [--findfiles FINDFILES]
                [--colorlike COLORLIKE] [--listcolors] [--brief]
                [--exportjson EXPORTJSON] [--importjson IMPORTJSON]
                [--searchtext SEARCHTEXT]

optional arguments:
  -h, --help            show this help message and exit
  --scan                scan filesystem
  --pal                 build palettes
  --killpal             kill palettes
  --killdupes           kill duplicate entries
  --hash                build file hashes
  --imghash             build image hashes
  --ocr                 ocr images
  --killocr             kill ocr images
  --ocrmask OCRMASK     ocr file mask for ilike
  --lang LANG           ocr language
  --random              open random image
  --findmaincolor FINDMAINCOLOR
                        list images with specified main colors. (ROYGBCMKLW)
  --findcolor FINDCOLOR
                        list images with specified colors (ROYGBCMKLW)
  --findfiles FINDFILES
                        list paths matchin pattern (ilike)
  --colorlike COLORLIKE
                        color search using ilike syntax (ROYGBCMKLW)
  --listcolors          list image colors
  --brief               print less stuff
  --exportjson EXPORTJSON
                        export database to file
  --importjson IMPORTJSON
                        import database from file
  --searchtext SEARCHTEXT
                        search text in db. Uses ilike pattern
```

So, what now?

## Filesystem scan

First, you `--scan`. This will cause the program to walk thorugh your paths and find all images that were added and removed and changed since the last time.

Then you `--hash`. This will calculate sha256 checksum for every single file, which is going to take a while if you have a million pictures in there.
This step is necessary because files come and go, and they also move, and their contents do not necessarily change. Therefore the tool uses sha256 to look up file information,
and not file path.

## Color scan

Now the fun part. Ignore --imghash for now, as it calculates dhashes for images, but they aren't used. Yet. (They will be to detect duplicates)

Let's say you want to find images by dominant color. For that you first build palette database by running the program with `--pal` keyword. This will be done for all hashed files that
have a disk path, and it will take a while. This operation will assign palette fingerprint to all known files, and you can kill that fingerprint with `--killpal` command.

## Color search

The fingerprint is composed from letters ROYGBCMLKW, where:

* R - Red
* O - Orange
* Y - Yellow
* G - Green
* B - Blue
* C - Cyan
* M - Magenta
* L - Gray
* K - Black.
* W - White.

It looks like "LKWC", where the most common colors come first. Those values are perceptive, meaning I personally sat and decided which of 216 colors corresponds (the images are converted to reduced RGB palette first)
to which letter, meaning it is not perfect. But it is good enough.

Once the build process is done (you can interrupt it with Ctrl+C, it will save work for palettes it already scanned), you can search by color.
For example, you want to find images which have Red as dominant color, then you use `imgdb --findmaincolor R` and it will print you 
all paths that have 'R' as their dominant color.

To find images that HAVE color red somewhere in palette you can do `imgdb --findcolor R` which will search for specified sequences within palettes at any position.

You can also use `--colorlike` which allows you to use ilike patterns from sql. For example `imgdb --colorlike "R%Y%"` will search for images that have R as dominant color, and have
Yellow somewhere else.

Adding `--brief` parameter will make the program print less scan.

## File search

`imgdb --findfiles <pattern>` where `<pattern>` is expression used for sql ilike. for example, `imgdb --findfiles "%cat%"` will list all files that have a word `cat` in their path. 
This will be faster than searching via filesystem.

## Ocr

To attempt to OCR you need tesseract installed, it needs to have languages installed, and command for starting it should be set in config.

To start OCR process you do `imgdb.py --ocr --lang <language>` where `<language>` is the language you want. If `--lang` is missing, it will default to `eng`. You can also limit OCR to
specific files by providing `--ocrmask <mask>` where `<mask>` is ilike pattern for filenames. For example `imgdb.py --ocr --lang jpn --ocrmask "japanese"` will only OCR files that
have "japanese" in their filename.

You can kill OCR for specific languages with `--killocr`, which will kill data for languages specified with `--lang` and if no language has been provided, it will nuke data for english.

## Searching OCR

`imgdb.py --searchtext "%CAT%"` or `imgdb.py --searchtext "%CAT%" --brief`. This will print files that have specified string in their OCR data.

## Import/Export database
The database data can be imported and exported with `--exportjson FILENAME.json` and `--importjson FILENAME.json`, where filename is whatever you want. The resulting file will be quite large,
and it is recommended to import onto blank database only.

## Random file.
`imgdb.py --random` this will open random file from the database using os command. 

## The End

And that's should be all. As I said, this is a pet project and it is completely unsupported. 

