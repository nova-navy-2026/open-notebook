/**
 * The closed object vocabulary supported by the RF-DETR detection engine.
 *
 * These names must match the COCO-91 lookup table the backend uses to filter
 * detections (`open_notebook/research/video_service.py::_COCO_CLASSES`). The
 * backend filters by class name from the (comma-separated) query string, so we
 * surface the exact class names here as a picker instead of a free-text field.
 *
 * Kept alphabetically sorted for easier scanning in the dropdown.
 */
export const COCO_CLASSES: string[] = [
  "airplane",
  "apple",
  "backpack",
  "banana",
  "baseball bat",
  "baseball glove",
  "bear",
  "bed",
  "bench",
  "bicycle",
  "bird",
  "boat",
  "book",
  "bottle",
  "bowl",
  "broccoli",
  "bus",
  "cake",
  "car",
  "carrot",
  "cat",
  "cell phone",
  "chair",
  "clock",
  "couch",
  "cow",
  "cup",
  "dining table",
  "dog",
  "donut",
  "elephant",
  "fire hydrant",
  "fork",
  "frisbee",
  "giraffe",
  "hair drier",
  "handbag",
  "horse",
  "hot dog",
  "keyboard",
  "kite",
  "knife",
  "laptop",
  "microwave",
  "motorcycle",
  "mouse",
  "orange",
  "oven",
  "parking meter",
  "person",
  "pizza",
  "potted plant",
  "refrigerator",
  "remote",
  "sandwich",
  "scissors",
  "sheep",
  "sink",
  "skateboard",
  "skis",
  "snowboard",
  "spoon",
  "sports ball",
  "stop sign",
  "suitcase",
  "surfboard",
  "teddy bear",
  "tennis racket",
  "tie",
  "toaster",
  "toilet",
  "toothbrush",
  "traffic light",
  "train",
  "truck",
  "tv",
  "umbrella",
  "vase",
  "wine glass",
  "zebra",
];

/** Parse a comma-separated query string into a list of trimmed class names. */
export function parseClasses(value: string): string[] {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

/** Serialize a list of selected class names back into the query string. */
export function serializeClasses(classes: string[]): string {
  return classes.join(", ");
}
