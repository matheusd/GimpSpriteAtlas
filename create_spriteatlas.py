#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# GIMP plug-in Create SpriteAtlas
# Take layers as images and compile into spriteatlas
# including a coordinates file in json/atlas/css/xml format
# uses rectangle packing algorithm
#
# https://github.com/BdR76/GimpSpriteAtlas/
# GIMP 3 Compatibility Changes by Roo

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gimp, GimpUi, GObject, GLib, Gio, Gegl
from util import mkenumvalue


import math
import os
from functools import total_ordering
import sys # Added for sys.argv in Gimp.main

layer_rects = []
spaces = []
pixel_space = 1
ATLAS_PLUGIN_VERSION = "v0.4-GIMP3" # Updated version

# empty space
@total_ordering
class spaceobj(object):
    def __init__(self, x, y, width, height):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
    # Replaced __cmp__ with __eq__ and __lt__ for Python 3 / total_ordering
    def __eq__(self, other):
        if not isinstance(other, spaceobj):
            return NotImplemented
        return (self.width * self.height == other.width * other.height)
    def __lt__(self, other):
        if not isinstance(other, spaceobj):
            return NotImplemented
        return (self.width * self.height < other.width * other.height)

# image layer metadata
@total_ordering
class imgRect(object):
    def __init__(self, n, w, h, i, layer_obj): # Added layer_obj
        # process stuff
        if n.endswith(('.png', '.jpg')):
            n = os.path.splitext(n)[0]
        # set parameters
        self.name = n
        self.width = w
        self.height = h
        self.index  = i # Keep original index if needed, but layer_obj is better
        self.layer = layer_obj # Store the actual layer object
        # extra stuff
        self.pack_x = 0
        self.pack_y = 0
        self.ext_up = 0
        self.ext_down = 0
        self.ext_left = 0
        self.ext_right = 0
        # determinate name and optional extend direction, example "green_pipe [ext=UD].png" -> name="green_pipe" ext_up=1 ext_down=1
        pos1 = n.find('[')
        pos2 = n.find(']')
        if pos1 >= 0 and pos2 >= 0 and pos1 < pos2:
            self.name = n[0:pos1].strip()
            ex = n[pos1+1:pos2].strip().lower()
            if ex.startswith("ext="):
                ex = ex[4:]
                self.ext_up = 1 if "u" in ex else 0
                self.ext_down = 1 if "d" in ex else 0
                self.ext_left = 1 if "l" in ex else 0
                self.ext_right = 1 if "r" in ex else 0
        # total width and height, including extruding parts
        self.tot_width = self.width + self.ext_left + self.ext_right
        self.tot_height = self.height + self.ext_up + self.ext_down

    # Replaced __cmp__ with __eq__ and __lt__ for Python 3 / total_ordering
    def __eq__(self, other):
        if not isinstance(other, imgRect):
            return NotImplemented
        return self.height == other.height
    def __lt__(self, other):
        if not isinstance(other, imgRect):
            return NotImplemented
        # Sort by height descending (so less than means greater height)
        return self.height > other.height # Note the change for descending sort

def prepare_layers_metadata(image): # Pass image object
    global layer_rects, spaces, pixel_space
    layer_rects = [] # Clear global list
    spaces = []      # Clear global list

    # Collect metadata from all layers as custom list
    layers = image.get_layers() # GIMP 3 API
    idx = 0
    area = 0
    maxWidth = 0
    for lyr in layers:
        if not lyr.get_visible(): # Skip invisible layers
             continue
        # layer image metadata
        n = lyr.get_name() # GIMP 3 API
        w = lyr.get_width() # GIMP 3 API
        h = lyr.get_height() # GIMP 3 API
        newrec = imgRect(n, w, h, idx, lyr) # Pass layer object
        layer_rects.append(newrec)
        # calculate total layer area and maximum layer width
        area += (newrec.tot_width + pixel_space) * (newrec.tot_height + pixel_space);
        maxWidth = max(newrec.tot_width + pixel_space, maxWidth + pixel_space)
        idx = idx + 1

    # sort the layer data for packing by height, descending
    layer_rects.sort() # Uses the __lt__ defined in imgRect

    # aim for a square-ish resulting container,
    # slightly adjusted for sub-100% space utilization
    startWidth = max(math.ceil(math.sqrt(area / 0.95)), maxWidth) if area > 0 else maxWidth

    # also initialise list of spaces, start with a single empty space based on average layer size
    spaces.append(spaceobj(0, 0, startWidth, (startWidth+startWidth)))
    return

def calc_layers_packing():
    global layer_rects, spaces, pixel_space
    # packing algorithm, explanation and code example by Volodymyr Agafonkin
    # https://observablehq.com/@mourner/simple-rectangle-packing
    for box in layer_rects:

        # look through spaces backwards so that we check smaller spaces first
        # Sort spaces smallest first to optimize finding a fit
        spaces.sort()
        found_space = False
        i = 0
        while i < len(spaces):
            space = spaces[i];

            # look for empty spaces that can accommodate the current box
            if (box.tot_width + pixel_space > space.width or box.tot_height + pixel_space > space.height):
                i += 1;
                continue;

            # found the space; add the box to its top-left corner
            # |-------|-------|
            # |  box  |       |
            # |_______|       |
            # |         space |
            # |_______________|
            box.pack_x = space.x + box.ext_left
            box.pack_y = space.y + box.ext_up

            if (box.tot_width + pixel_space == space.width and box.tot_height + pixel_space == space.height):
                # space matches the box exactly; remove it
                del spaces[i] # More efficient removal

            elif (box.tot_height + pixel_space == space.height):
                # space matches the box height; update it accordingly
                # |-------|---------------|
                # |  box  | updated space |
                # |_______|_______________|
                spaces[i].x += (box.tot_width + pixel_space);
                spaces[i].width -= (box.tot_width + pixel_space);
            elif (box.tot_width + pixel_space == space.width):
                # space matches the box width; update it accordingly
                # |---------------|
                # |      box      |
                # |_______________|
                # | updated space |
                # |_______________|
                spaces[i].y += (box.tot_height + pixel_space);
                spaces[i].height -= (box.tot_height + pixel_space);
            else:
                # otherwise the box splits the space into two spaces
                # |-------|-----------|
                # |  box  | new space |
                # |_______|___________|
                # | updated space     |
                # |___________________|
                # Add the new space first
                spaces.append(spaceobj(space.x + box.tot_width + pixel_space, space.y, space.width - (box.tot_width + pixel_space), box.tot_height + pixel_space));
                # Update the existing space
                spaces[i].y += (box.tot_height + pixel_space);
                spaces[i].height -= (box.tot_height + pixel_space);

            found_space = True
            break # Exit the inner loop once space is found

        if not found_space:
             # This should ideally not happen if startWidth is calculated correctly
             # but as a fallback, we might need to expand the canvas conceptually
             # For now, log or raise an error
             print(f"Warning: Could not find space for layer {box.name}")


    return

# Helper to copy/paste regions (simplified)
def copy_paste_layer_region(src_layer, dest_layer, src_x, src_y, width, height, dest_x, dest_y):
    # GIMP 3 uses non-destructive editing principles more often.
    # Direct copy/paste between layers might involve buffers or temporary layers.
    # Gimp.PixelRegion is the preferred way for pixel data transfer.

    # 1. Get PixelRegion from source
    src_buffer = src_layer.get_buffer()
    if not src_buffer:
        print(f"Error: Could not get buffer for layer {src_layer.get_name()}")
        return
    src_rect = Gegl.Rectangle.new(src_x, src_y, width, height)
    # Ensure we don't read outside source layer bounds
    src_rect.intersect(Gegl.Rectangle.new(0, 0, src_layer.get_width(), src_layer.get_height()), src_rect)
    if src_rect.is_empty():
        return # Nothing to copy from this region

    # Adjust dest_x/y if src_rect was clipped at the top/left
    clipped_dx = dest_x + (src_rect.x - src_x)
    clipped_dy = dest_y + (src_rect.y - src_y)

    # 2. Get PixelRegion for destination
    dest_buffer = dest_layer.get_buffer()
    if not dest_buffer:
        print(f"Error: Could not get buffer for layer {dest_layer.get_name()}")
        return
    dest_rect = Gegl.Rectangle.new(clipped_dx, clipped_dy, src_rect.width, src_rect.height)
    # Ensure we don't write outside destination layer bounds
    dest_rect.intersect(Gegl.Rectangle.new(0, 0, dest_layer.get_width(), dest_layer.get_height()), dest_rect)
    if dest_rect.is_empty():
        return # Cannot paste into this region

    # Ensure source and destination rects match after clipping
    final_width = dest_rect.width
    final_height = dest_rect.height
    src_rect.width = final_width
    src_rect.height = final_height
    
    print(f"XXXXXX copying {final_width}:{final_height}")

    # 3. Copy data
    # Gimp.buffer_copy is efficient for this
    # Gimp.buffer_copy(
    #     src_buffer,            # Source buffer
    #     src_rect,              # Source rectangle
    #     Gimp.OrientationType.HORIZONTAL, # Orientation (not relevant for simple copy)
    #     dest_buffer,           # Destination buffer
    #     dest_rect.x,           # Destination x
    #     dest_rect.y            # Destination y
    # )
    src_buffer.copy(src_rect, Gegl.AbyssPolicy.NONE, dest_buffer, dest_rect)
    dest_buffer.flush()
    
    
    # Mark destination region as modified
    # dest_layer.merge_buffer(dest_buffer, dest_rect)
    # dest_layer.update(dest_rect.x, dest_rect.y, dest_rect.width, dest_rect.height)



def render_spriteatlas(image, filetag): # Pass original image
    global layer_rects, spaces, pixel_space
    # render output atlas based on current layer coordinates

    # determine total width, height
    img_w = 0
    img_h = 0
    for obj in layer_rects:
        w = obj.pack_x + obj.width + obj.ext_right
        h = obj.pack_y + obj.height + obj.ext_down # Corrected: use ext_down for height calc
        img_w = max(img_w, w)
        img_h = max(img_h, h)

    if img_w <= 0 or img_h <= 0:
         print("Warning: Calculated atlas size is zero or negative. No layers processed?")
         return None, 0, 0 # Indicate failure

    # create new image
    # Use RGBA for transparency support by default
    imgAtlas = Gimp.Image.new(img_w, img_h, Gimp.ImageBaseType.RGB)
    # Use Gimp.Layer.new()
    newLayer = Gimp.Layer.new(imgAtlas, filetag, img_w, img_h, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL) # Opacity is float 0-100
    imgAtlas.insert_layer(newLayer, None, 0) # Insert layer at the top

    # copy all layers to new positions using PixelRegion
    for obj in layer_rects:
        src_layer = obj.layer # Get the layer object stored earlier

        # Copy the main part of the layer
        copy_paste_layer_region(src_layer, newLayer,
                                0, 0, obj.width, obj.height, # Source region (full layer)
                                obj.pack_x, obj.pack_y)      # Destination position

        # Extrude edges using copy_paste_layer_region
        if obj.ext_up == 1: # up
            copy_paste_layer_region(src_layer, newLayer, 0, 0, obj.width, 1, obj.pack_x, obj.pack_y - 1)
        if obj.ext_down == 1: # down
            copy_paste_layer_region(src_layer, newLayer, 0, obj.height - 1, obj.width, 1, obj.pack_x, obj.pack_y + obj.height)
        if obj.ext_left == 1: # left
            copy_paste_layer_region(src_layer, newLayer, 0, 0, 1, obj.height, obj.pack_x - 1, obj.pack_y)
        if obj.ext_right == 1: # right
            copy_paste_layer_region(src_layer, newLayer, obj.width - 1, 0, 1, obj.height, obj.pack_x + obj.width, obj.pack_y)


    # Watermark code removed for GIMP 3 conversion simplicity.
    # Implementing this correctly requires Gimp.PixelRegion manipulation.

    # No need to merge layers as we drew directly onto the target layer buffer

    # Create and show a new image window for our spritesheet
    Gimp.Display.new(imgAtlas)
    Gimp.displays_flush() # Still useful

    return imgAtlas, img_w, img_h # Return the new image object and dimensions

# --- Output Functions ---
# Use 'with open' for Python 3 file handling

def write_spriteatlas_jsonarray(filename, filetag, sizex, sizey):
    global layer_rects
    stroutput = "{\n\t\"frames\":["

    # insert all sprite metadata
    frames_data = []
    for obj in layer_rects:
        frame_str = ('\n\t\t{"filename":"%s","frame":{"x":%d,"y":%d,"w":%d,"h":%d},"rotated":false,"trimmed":false,' % (obj.name, obj.pack_x, obj.pack_y, obj.width, obj.height)
                   + '"spriteSourceSize":{"x":0,"y":0,"w":%d,"h":%d},' % (obj.width, obj.height)
                   + '"sourceSize":{"w":%d,"h":%d}}' % (obj.width, obj.height))
        frames_data.append(frame_str)

    stroutput += ",".join(frames_data)

    # meta data
    stroutput += "\n\t],\n"
    stroutput += "\t\"meta\":{\n"
    stroutput += "\t\t\"app\":\"https://github.com/BdR76/GimpSpriteAtlas/\",\n"
    stroutput += f"\t\t\"version\":\"GIMP SpriteAtlas plug-in {ATLAS_PLUGIN_VERSION}\",\n"
    stroutput += "\t\t\"author\":\"Bas de Reuver\",\n"
    stroutput += f"\t\t\"image\":\"{filetag}.png\",\n"
    stroutput += f"\t\t\"size\":{{\"w\":{sizex},\"h\":{sizey}}},\n"
    stroutput += "\t\t\"scale\":1\n"
    stroutput += "\t}\n"
    stroutput += "}"

    # export filename
    outputname = f'{filename}.json'

    # export coordinate variables to textfile
    try:
        with open(outputname, 'w', encoding='utf-8') as outputfile:
            outputfile.write(stroutput)
    except IOError as e:
        print(f"Error writing JSON Array file {outputname}: {e}")
    return

def write_spriteatlas_jsonhash(filename, filetag, img_w, img_h):
    global layer_rects
    stroutput = "{\n\t\"frames\":{"

    # insert all sprite metadata
    frames_data = []
    for obj in layer_rects:
        frame_str = ('\n\t\t"%s":{"frame":{"x":%d,"y":%d,"w":%d,"h":%d},"rotated":false,"trimmed":false,' % (obj.name, obj.pack_x, obj.pack_y, obj.width, obj.height)
                   + '"spriteSourceSize":{"x":0,"y":0,"w":%d,"h":%d},' % (obj.width, obj.height)
                   + '"sourceSize":{"w":%d,"h":%d}}' % (obj.width, obj.height))
        frames_data.append(frame_str)

    stroutput += ",".join(frames_data)

    # meta data
    stroutput += "\n\t},\n"
    stroutput += "\t\"meta\":{\n"
    stroutput += "\t\t\"app\":\"https://github.com/BdR76/GimpSpriteAtlas/\",\n"
    stroutput += f"\t\t\"version\":\"GIMP SpriteAtlas plug-in {ATLAS_PLUGIN_VERSION}\",\n"
    stroutput += "\t\t\"author\":\"Bas de Reuver\",\n"
    stroutput += f"\t\t\"image\":\"{filetag}.png\",\n"
    stroutput += f"\t\t\"size\":{{\"w\":{img_w},\"h\":{img_h}}},\n"
    stroutput += "\t\t\"scale\":1\n"
    stroutput += "\t}\n"
    stroutput += "}"

    # export filename
    outputname = f'{filename}.json'

    # export coordinate variables to textfile
    try:
        with open(outputname, 'w', encoding='utf-8') as outputfile:
            outputfile.write(stroutput)
    except IOError as e:
        print(f"Error writing JSON Hash file {outputname}: {e}")
    return

def write_spriteatlas_libgdx(filename, filetag, img_w, img_h):
    global layer_rects
    stroutput = (f"{filetag}.png\nsize: {img_w},{img_h}\nformat: RGBA8888\nfilter: Linear,Linear\nrepeat: none\n")

    # insert all sprite metadata
    for obj in layer_rects:
        stroutput +=  (f"{obj.name}\n  rotate: false\n  xy: {obj.pack_x}, {obj.pack_y}\n  size: {obj.width}, {obj.height}\n  orig: {obj.width}, {obj.height}\n  offset: 0, 0\n  index: -1\n")

    # export filename
    outputname = f'{filename}.atlas'

    # export coordinate variables to textfile
    try:
        with open(outputname, 'w', encoding='utf-8') as outputfile:
            outputfile.write(stroutput)
    except IOError as e:
        print(f"Error writing libGDX file {outputname}: {e}")
    return

def write_spriteatlas_css(filename, filetag):
    global layer_rects
    stroutput = f"/* GIMP SpriteAtlas plug-in {ATLAS_PLUGIN_VERSION} by Bas de Reuver */\n" # Removed year for less maintenance

    # insert all sprite metadata
    for obj in layer_rects:
        # CSS class names should be sanitized
        css_class_name = Gimp.canonize_identifier(obj.name, '_') # Basic sanitization
        stroutput += f".{css_class_name} {{\n"
        stroutput += f"\tbackground: url('{filetag}.png') no-repeat -{obj.pack_x}px -{obj.pack_y}px;\n"
        stroutput += f"\twidth: {obj.width}px;\n"
        stroutput += f"\theight: {obj.height}px;\n"
        stroutput += "}\n"

    # export filename
    outputname = f'{filename}.css'

    # export coordinate variables to textfile
    try:
        with open(outputname, 'w', encoding='utf-8') as outputfile:
            outputfile.write(stroutput)
    except IOError as e:
        print(f"Error writing CSS file {outputname}: {e}")
    return


def write_spriteatlas_xml(filename, filetag):
    global layer_rects
    stroutput = (f'<TextureAtlas imagePath="{filetag}.png">\n') # Removed xmlns, less common for simple XML data
    stroutput += f'\t<!-- GIMP SpriteAtlas plug-in {ATLAS_PLUGIN_VERSION} by Bas de Reuver -->\n' # Removed year

    # insert all sprite metadata
    for obj in layer_rects:
        stroutput += f'\t<SubTexture name="{obj.name}" x="{obj.pack_x}" y="{obj.pack_y}" width="{obj.width}" height="{obj.height}"/>\n' # Use self-closing tag

    stroutput += '</TextureAtlas>\n'

    # export filename
    outputname = f'{filename}.xml'

    # export coordinate variables to textfile
    try:
        with open(outputname, 'w', encoding='utf-8') as outputfile:
            outputfile.write(stroutput)
    except IOError as e:
        print(f"Error writing XML file {outputname}: {e}")
    return

# --- Main Plugin Logic ---

def run_create_spriteatlas(procedure, run_mode, image, drawables, args, data):
    if run_mode == Gimp.RunMode.INTERACTIVE:
        GimpUi.init('python-fu-test-dialog')
        Gegl.init(None)
        dialog = GimpUi.ProcedureDialog(procedure=procedure, config=args)
        dialog.fill(None)
        if not dialog.run():
            dialog.destroy()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        else:
            dialog.destroy()

    
    
    global pixel_space, layer_rects

    # Get arguments using GObject introspection
    filetag = args.get_property("fileName")
    foldername_giofile = args.get_property("outputFolder") # This is a Gio.File
    outputtype = args.get_property("fileType")
    padding = args.get_property("addPadding")

    # Convert Gio.File to path string
    foldername = foldername_giofile.get_path() if foldername_giofile else GLib.get_tmp_dir() # Use temp dir if None

    if not foldername or not os.path.isdir(foldername):
         # Use Gimp.message or return an error status
         Gimp.message(f"Output folder '{foldername}' is not valid. Please select a valid directory.")
         return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error()) # Indicate failure


    # add 1 pixel padding
    pixel_space = 1 if padding else 0

    # Clear any selections on the original image
    # image.selection_none() # GIMP 3 API // FIXME: needed?

    prepare_layers_metadata(image) # Pass image

    if not layer_rects:
        Gimp.message("No visible layers found to process.")
        return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

    # export filename(s) - Use os.path.join for cross-platform compatibility
    output_basename = os.path.join(foldername, filetag)

    # compile image
    calc_layers_packing()
    imgAtlas, img_w, img_h = render_spriteatlas(image, filetag) # Pass original image

    if imgAtlas is None:
        Gimp.message("Failed to render the sprite atlas image.")
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error())

    # Save the atlas image using Gimp.file_save
    try:
        # Construct Gio.File for saving
        png_filename = f"{output_basename}.png"
        png_file = Gio.File.new_for_path(png_filename)

        # Gimp.file_save expects drawables as a list/array
        # drawable_list = imgAtlas.get_layers()
        # drawable_to_save = drawable_list[0] # Fallback to first layer

        Gimp.file_save(run_mode, imgAtlas, png_file, None) 

    except Exception as e:
        error_message = f"Failed to save atlas image {png_filename}: {e}"
        Gimp.message(error_message)
        # Clean up the created image if saving failed
        Gimp.Image.delete(imgAtlas)
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(error_message))


    # write coordinate file
    try:
        if outputtype == "JSON Array":
            write_spriteatlas_jsonarray(output_basename, filetag, img_w, img_h)
        elif outputtype == "JSON Hash":
            write_spriteatlas_jsonhash(output_basename, filetag, img_w, img_h)
        elif outputtype == "libGDX":
            write_spriteatlas_libgdx(output_basename, filetag, img_w, img_h)
        elif outputtype == "CSS":
            write_spriteatlas_css(output_basename, filetag)
        else: # outputtype == 5
            write_spriteatlas_xml(output_basename, filetag)
    except Exception as e:
         # Log error, maybe inform user
         print(f"Error writing coordinate file: {e}")
         Gimp.message(f"Error writing coordinate file: {e}")
         # Don't necessarily fail the whole plugin if only coord file fails,
         # but maybe return a different status or warning.

    # Return success
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


# --- GIMP 3 Plugin Registration ---

class SpriteAtlasPlugin(Gimp.PlugIn):
    ## GObject virtual methods ##
    def do_set_i18n(self, procname):
        return False, '', None
    
    def do_query_procedures(self):
        # Procedure name for GIMP PDB
        return ['python-fu-create-spriteatlas']

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(self, name,
                                       Gimp.PDBProcType.PLUGIN,
                                       run_create_spriteatlas, None) # run_func, data

        procedure.set_image_types("*") # Applicable image types
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE | Gimp.ProcedureSensitivityMask.DRAWABLES | Gimp.ProcedureSensitivityMask.NO_DRAWABLES) # When it's active
        procedure.set_menu_label("Create SpriteAtlas...")
        procedure.set_attribution("Bas de Reuver", "Bas de Reuver", "2023-2024") # Author, Copyright, Year
        procedure.add_menu_path("<Image>/Filters/Animation")

        # Define arguments using GObject ParamSpecs
        # (PF_IMAGE is implicit 'image' parameter)

        # (PF_STRING, "fileName", "Export file name (without extension):", "sprites")
        procedure.add_string_argument(name="fileName",
                                     nick="Export file name",
                                     blurb="Export file name (without extension)",
                                     value="sprites",
                                     flags=GObject.ParamFlags.READWRITE)

        # (PF_DIRNAME, "outputFolder", "Export to folder:", "/tmp") -> Gio.File
        procedure.add_file_argument(name="outputFolder",
                                     nick="Export to folder",
                                     blurb="Select the folder to export the atlas and coordinate file",
                                     action=Gimp.FileChooserAction.CREATE_FOLDER,
                                     none_ok=False,
                                     default_file=Gio.File.new_for_path(GLib.get_tmp_dir()), # Default to temp dir
                                     flags=GObject.ParamFlags.READWRITE)

        ft_choices = Gimp.Choice()
        ft_choices.add(nick="JSON Array", id=0, label="JSON Array (TexturePacker)", help="")
        ft_choices.add(nick="JSON Hash",  id=0, label="JSON Hash (TexturePacker)", help="")
        ft_choices.add(nick="libGDX",     id=0, label="libGDX TextureAtlas", help="")
        ft_choices.add(nick="CSS",        id=0, label="CSS", help="")
        ft_choices.add(nick="XML",        id=0, label="XML", help="")
        

        procedure.add_choice_argument(name="fileType",
                                   nick="Export file type",
                                   blurb="Select the format for the coordinate file",
                                   choice=ft_choices,
                                   value="JSON Array", # Default to JSON Array
                                   flags=GObject.ParamFlags.READWRITE)

        # (PF_BOOL, "addPadding", "Pad one pixel between sprites:", TRUE)
        procedure.add_boolean_argument(name="addPadding",
                                      nick="Add Padding",
                                      blurb="Pad one pixel between sprites",
                                      value=True,
                                      flags=GObject.ParamFlags.READWRITE)

        return procedure

# Register the plugin class with GIMP
Gimp.main(SpriteAtlasPlugin.__gtype__, sys.argv)