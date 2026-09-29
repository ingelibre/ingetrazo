# Assembly Animation

Open **Extensions → Assembly Animation**. Make each moving part a separate
 top-level group first, and position the parts in their assembled starting pose.
Exit group editing before opening the extension.

1. Choose a **Moving part** and its **Parent part**. World is stationary.
2. Choose **Fixed attachment**, **Hinge rotation**, or **Straight slot / travel line**.
3. For a hinge, enter the pivot's world X, Y, Z coordinates in millimetres and
   an axis direction (for example `0, 0, 1` for vertical). Start/end are degrees.
4. For straight travel, position the pin centre at the desired starting point,
   enter the travel direction, and set start/end offsets in millimetres.
   Allow for pin radius at each slot end. Selecting a loose edge *before*
   opening the extension lets **Use selected edge** fill the direction and
   length; for a hinge it also fills the anchor. It does not relocate the pin.
5. Click **Add / replace joint for moving part**. Repeat for other parts.
6. Drag the percentage slider or use **Play/Pause**. All joints run through
   their own start/end ranges together. Fixed children follow their parents.
7. **Keep pose and joints** records the pose and constraints in one undo step.
   Save the model as `.igz` to retain them. **Cancel** restores the original
   pose and discards changes. **Return to original pose** restores the pose
   from when you opened the dialog, while retaining the joint configuration.

Example: attach a wing to the drone body using a hinge, enter its hinge point,
set the axis along its hinge, and set angles 0 to 90. Attach an item to that
wing using a fixed attachment to have it move with the wing.

The pin's travel is a bounded straight centreline, not a shape collision solver.
You specify safe offsets that keep the physical pin inside the slot. Curved
slots, arbitrary enclosing shapes, contact, forces and closed crank/connecting
rod mechanisms are not supported yet. A part has one parent; cycles are rejected.
Constraints apply in this animation dialog, not to ordinary Move/Rotate tools.
If you reposition parts manually, recreate their affected joints at the new pose.
Nested parts should be exposed as separate top-level groups before rigging.
