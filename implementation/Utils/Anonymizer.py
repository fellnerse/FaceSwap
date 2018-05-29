import torch
from pathlib import Path

import numpy as np
from PIL.Image import BICUBIC, LANCZOS
from torchvision.transforms import ToTensor, ToPILImage

from Preprocessor.FaceExtractor import FaceExtractor
from Preprocessor.FaceReconstructor import FaceReconstructor


class Anonymizer:
    def __init__(self, model_folder: str, config) -> None:
        """
        :param model_folder: Path to models folder.
        """
        self.config = config
        self.model_folder = Path(model_folder)
        self.model = config['model'](**config['model_params'])
        self.model.load_model(self.model_folder)

        # use extractor and transform later get correct input for network
        self.extractor = FaceExtractor(sharp_edge=False, margin=0.05, mask_factor=10)
        self.reconstructor = FaceReconstructor(mask_factor=-20)

    def __call__(self, image):
        """
        Merges an anonymized face on the scene
        :param image: PIL image
        :return: PIL image
        """
        constructed_image = None
        # Extract face
        extracted_face, extracted_information = self.extractor(image)
        if extracted_face is not None:
            latent_information = self.model.img2latent_bridge(extracted_face, extracted_information)
            # feed into network
            face_out = self.model.anonymize(latent_information).squeeze(0)
            # get it back to the cpu and get the data
            face_out = ToPILImage()(face_out.cpu().detach())
            # scale to original resolution
            face_out = face_out.resize(extracted_face.size, resample=BICUBIC)

            # Constructed scene with new face
            constructed_image = self.reconstructor(face_out, extracted_information)

        return constructed_image