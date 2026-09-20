"""Rotation in clockwise image coordinates; source and output transforms are independent."""
import math

import cv2
import numpy as np


def round_style(value):
    return math.copysign(math.floor(abs(value) + .5), value)


def rotated_bounds(x, y, width, height, angle=0):
    theta = math.radians(angle)
    w = abs(width * math.cos(theta)) + abs(height * math.sin(theta))
    h = abs(width * math.sin(theta)) + abs(height * math.cos(theta))
    return x + (width-w)/2, y + (height-h)/2, w, h


def source_frame(image, region):
    """Deskew only the original text crop, returning its local-to-page affine map.

    Changing output rotation never changes what is erased or sampled from source.
    OCR quadrilaterals delimit a rotated line; perspective/curved lettering is not
    reconstructed by this rigid rotation model.
    """
    angle = float(region.get('source_rotation', 0))
    if abs(angle) < .01:
        return image, region['bbox'], None
    theta = math.radians(angle)
    rotation = np.array([[math.cos(theta), -math.sin(theta)],
                         [math.sin(theta), math.cos(theta)]], dtype=float)
    quad = region.get('source_quad')
    if quad is None:
        x, y, w, h = region['bbox']
        quad = [[x,y],[x+w,y],[x+w,y+h],[x,y+h]]
    aligned = np.asarray(quad, dtype=float) @ rotation
    low, high = aligned.min(axis=0)-4, aligned.max(axis=0)+4
    width, height = np.ceil(high-low).astype(int)
    if width < 3 or height < 3 or width*height > 40_000_000:
        raise ValueError('倾斜文字范围无效或过大。')
    origin = rotation @ low
    matrix = np.column_stack((rotation.T, -low))
    frame = cv2.warpAffine(image, matrix, (int(width), int(height)),
                           flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return frame, [0,0,int(width),int(height)], (rotation, origin, angle)


def source_position(x, y, width, height, transform):
    if transform is None:
        return {'x':round(x,2), 'y':round(y,2), 'rotation':0}
    rotation, origin, angle = transform
    center = rotation @ np.array([x+width/2,y+height/2]) + origin
    return {'x':round(float(center[0]-width/2),2),
            'y':round(float(center[1]-height/2),2), 'rotation':round(angle,2)}
