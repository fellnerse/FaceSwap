from Configuration.config_general import *
from Models.CGAN.CGAN import CGAN
from Models.CPGGAN.CPGGAN import CPGGAN
from Models.DCGAN.DCGAN import DCGAN
from Models.DeepFake.Autoencoder import AutoEncoder
from Models.DeepFake.Decoder import Decoder
from Models.DeepFake.DeepFakeOriginal import DeepFakeOriginal
from Models.DeepFake.Encoder import Encoder
from Models.LatentGAN.LatentGAN import LatentGAN
from Models.LatentModel.Decoder import LatentDecoder
from Models.LatentModel.LatentModel import LowResModel, RetrainLowResModel
from Models.PGGAN.PGGAN import PGGAN
from Utils.ImageDataset import *


class Config:
    batch_size = 64
    validation_size = 0.2
    model = None
    model_params = None

    @staticmethod
    def data_set():
        raise NotImplementedError()

    max_epochs = 101
    validate_index = 0
    validation_frequencies = [2, 5, 20]
    validation_periods = [0, 10, 20, max_epochs + 1]

    save_model_every_nth = 20


class Deep_Fakes_Config(Config):
    model = DeepFakeOriginal
    model_params = {'encoder': lambda: Encoder(input_dim=(3, 128, 128),
                                               latent_dim=1024,
                                               num_convblocks=5),
                    'decoder': lambda: Decoder(input_dim=512,
                                               num_convblocks=4),
                    'auto_encoder': AutoEncoder,
                    'select_autoencoder': 1}

    @staticmethod
    def data_set():
        return ImageDatesetCombined(Path(SIMONE_MERKEL), size_multiplicator=100,
                                    img_size=(128, 128))


class LowResConfig(Config):
    batch_size = 256
    model = LowResModel
    model_params = {'decoder': lambda: LatentDecoder(72 * 2 + 8 * 8 * 3),
                    'lr': 1e-4}

    @staticmethod
    def data_set():
        return ImageFeatureDataset(ARRAY_IMAGES_128,
                                   [ARRAY_LANDMARKS, ARRAY_LOWRES_8])


class RetrainConfig(LowResConfig):
    model = RetrainLowResModel
    model_params = {'model_path': '/nfs/students/summer-term-2018/project_2/models/latent_model/model',
                    }
    model_params.update(LowResConfig.model_params)
    dataset = lambda: ImageFeatureDataset(ARRAY_IMAGES_128,
                                          [ARRAY_LANDMARKS, ARRAY_LOWRES_8])


class GAN_CONFIG(Config):
    @staticmethod
    def data_set():
        raise NotImplementedError()

    validation_size = 0.005  # no validation in GAN models -> set very small value, s.t. splitting works
    validation_frequencies = [1, 1, 1]
    save_model_every_nth = 2


class DCGAN_CONFIG(GAN_CONFIG):
    model = DCGAN
    batch_size = 16
    model_params = {
        'image_size': (64, 64, 3),
        'nz': 100,
        'ngf': 64,
        'ndf': 64,
        'lrG': 0.0002,
        'lrD': 0.0002,
        'beta1': 0.5,
        'beta2': 0.999
    }

    @staticmethod
    def data_set():
        return ImageFeatureDataset(ARRAY_IMAGES_64, None)


class CGAN_CONFIG(GAN_CONFIG):
    # Training with conditioning on landmarks and low resolution pixel maps is instable
    # therefore, the corresponding options are commented
    model = CGAN
    batch_size = 16
    model_params = {'y_dim': 2 * 10,  # only landmarks
                    # 'y_dim': 2 * 10,  + 3 * 2 * 2,  # landmarks & lowres
                    'z_dim': 100,
                    'ngf': 64,
                    'ndf': 64,
                    'lrG': 0.0002,
                    'lrD': 0.0002,
                    'beta1': 0.5,
                    'beta2': 0.999,
                    'lm_mean': ARRAY_LANDMARKS_10_MEAN,
                    'lm_cov': ARRAY_LANDMARKS_10_COV,
                    # 'lr_mean': ARRAY_LOWRES_2_MEAN,
                    # 'lr_cov': ARRAY_LOWRES_2_COV,
                    }

    @staticmethod
    def data_set():
        return ImageFeatureDataset(ARRAY_IMAGES_64, [ARRAY_LANDMARKS_10])
        # return ImageFeatureDataset(ARRAY_IMAGES_64, [ARRAY_LANDMARKS_10, ARRAY_LOWRES_2])


class LGAN_CONFIG(GAN_CONFIG):
    model = LatentGAN
    batch_size = 64
    model_params = {
        'input_dim': 72 * 2 + 8 * 8 * 3,
        'img_dim': (128, 128, 3),
        'z_dim': 44,
        'ndf': 64,
        'lrD': 0.00005,
        'alpha': 0.5
    }

    @staticmethod
    def data_set():
        return ImageFeatureDataset(ARRAY_IMAGES_128, [ARRAY_LANDMARKS, ARRAY_LOWRES_8])


class PGGAN_CONFIG(GAN_CONFIG):
    model = PGGAN
    target_resolution = 128
    if not np.log2(target_resolution).is_integer():
        raise ValueError
    max_level = int(np.log2(target_resolution)) - 1
    epochs_fade = 4
    epochs_stab = 4
    # No fading on first layer
    # Additional stabilization at the end
    max_epochs = (max_level + 1) * epochs_stab + (max_level - 1) * epochs_fade
    model_params = {'target_resolution': target_resolution,
                    'latent_size': 512,
                    'lrG': 0.0001,
                    'lrD': 0.0001,
                    'beta1': .0,
                    'beta2': 0.99,
                    'epochs_fade': epochs_fade,
                    'epochs_stab': epochs_stab,
                    'level_with_multiple_gpus': 4,
                    'batch_size_schedule': {1: 64, 2: 64, 3: 64, 4: 32, 5: 16, 6: 16},
                    # Resolutions:          4      8     16     32     64    128
                    }
    batch_size = model_params['batch_size_schedule'][1]

    @staticmethod
    def data_set():
        return ProgressiveFeatureDataset(None, initial_resolution=2)


class CPGGAN_CONFIG(PGGAN_CONFIG):
    model = CPGGAN
    target_resolution = 128
    model_params = {'feature_size': 2 * 10 + 3 * 2 * 2,
                    'lrG': 0.0001,
                    'lrD': 0.0001,
                    'lm_mean': ARRAY_LANDMARKS_10_MEAN,
                    'lm_cov': ARRAY_LANDMARKS_10_COV,
                    'lr_mean': ARRAY_LOWRES_2_MEAN,
                    'lr_cov': ARRAY_LOWRES_2_COV,
                    }
    model_params.update(PGGAN_CONFIG.model_params)
    model_params['target_resolution'] = target_resolution


    @staticmethod
    def data_set():
        return ProgressiveFeatureDataset([ARRAY_LANDMARKS_10, ARRAY_LOWRES_2], initial_resolution=2)


current_config = CPGGAN_CONFIG
