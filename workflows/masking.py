from nipype.pipeline.engine import Workflow, MapNode, Node
from nipype.interfaces.utility import IdentityInterface
import interfaces.nipype_interface_masking as masking_interfaces


def masking_workflow(masking_type='phase-based', threshold=0.5):
    wf = Workflow(name=masking_type + "_workflow")
    
    inputnode = MapNode(
        interface=IdentityInterface(
            fields=['phase', 'mag']),
        iterfield=['phase', 'mag'],
        name='inputnode')
    
    outputnode = MapNode(
        interface=IdentityInterface(
            fields=['mask']),
        iterfield=['mask'],
        name='outputnode')
    
    if masking_type == "hagberg-phase-based":
        pb_mask = MapNode(
            interface=masking_interfaces.PbMaskingInterface(),
            iterfield=['phase'],
            name='hagberg-phase-based-masking'
        )
        wf.connect([
            (inputnode, pb_mask, [('phase', 'phase')]),
            (pb_mask, outputnode, [('mask', 'mask')])
        ])        
        
    elif masking_type == "romeo":
        romeo = MapNode(
            interface=romeo_interface.RomeoInterface(),
            iterfield=['phase', 'mag'],
            name='phase_unwrap_romeo'
        )
        wf.connect([
            (inputnode, romeo, [('wrapped_phase', 'phase'),
                                ('mag', 'mag')]),
            (romeo, outputnode, [('out_file', 'unwrapped_phase')])
        ])
        
    elif masking_type == "romeoB0":
        romeo = Node(
        interface=romeo_interface.RomeoB0Interface(),
        name='phase_unwrap_romeo_B0'
        )
        wf.connect([
            (inputnode, romeo, [('wrapped_phase', 'phase'),
                                ('mag', 'mag'),
                                ('TE', 'TE')]),
            (romeo, outputnode, [('unwrapped_phase', 'unwrapped_phase'),
                                ('B0', 'B0')])
        ])
        
    return wf
